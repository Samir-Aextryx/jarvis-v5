//! Bounded goal execution with durable progress and no replay of completed steps.

use crate::email::is_email_request;
use crate::host::{self, fs};
use crate::intents::normalize_request;
use crate::local_pc::LocalPc;
use crate::pc_control::{self, Cancel};
use crate::speech::{remember_english, with_timeout};
use crate::ws::WebSocket;
use futures::future::{AbortHandle, abortable, join_all};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::cell::{Cell, RefCell};
use std::collections::{HashSet, VecDeque};
use std::rc::Rc;
use wasm_bindgen_futures::spawn_local;

// A ceiling for the whole goal; planners and UI steps have their own short deadlines.
const TASK_TIMEOUT_MS: f64 = 300_000.0;
const MAX_QUEUED_TASKS: usize = 4;
const READ_ACTIONS: [&str; 3] = ["read_file", "list_folder", "read_email"];
const TRANSIENT_READ_FAILURES: [&str; 11] = [
    "temporary network error", "network unavailable", "network timeout", "timed out", "timeout", "temporarily unavailable", "connection reset",
    "connection lost", "connection timed out", "please try again", "pc planning is unavailable",
];

thread_local! {
    static ACTIVE_IDS: RefCell<HashSet<String>> = RefCell::new(HashSet::new());
}

fn is_read(action: &str) -> bool {
    READ_ACTIONS.contains(&action)
}
fn is_open(action: &str) -> bool {
    action == "open_app" || action == "open_url"
}
fn transient_read_failure(result: &str) -> bool {
    let text = result.to_lowercase();
    TRANSIENT_READ_FAILURES.iter().any(|m| text.contains(m))
}
fn now_ms() -> f64 {
    host::now_secs() * 1000.0
}
fn s(v: &Value, k: &str) -> String {
    v[k].as_str().unwrap_or("").to_string()
}
fn target_text(step: &Value) -> String {
    match &step["target"] {
        Value::String(t) => t.clone(),
        Value::Array(a) => a.iter().filter_map(Value::as_str).collect::<Vec<_>>().join(", "),
        _ => String::new(),
    }
}

pub fn goal_request(text: &str) -> Option<String> {
    let normalized = normalize_request(text);
    crate::re!(r"(?is)^(?:autonomous task|your task is|deine aufgabe ist|erledige selbstständig|erledige selbständig|erledige autonom|solve this task|take care of|handle this task|kümmere dich um|kümmer dich um)\s*[:,-]?\s+(.+)$")
        .captures(&normalized)
        .map(|c| c[1].trim().to_string())
}

#[derive(Serialize, Deserialize, Clone, Default)]
pub struct Row {
    pub action: String,
    pub target: String,
    pub state: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub attempts: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub duration_ms: Option<u64>,
}

#[derive(Serialize, Deserialize, Clone, Default)]
pub struct Job {
    pub id: String,
    pub goal: String,
    pub state: String,
    pub steps: Vec<Row>,
    pub started: f64,
    pub rounds: u32,
    pub duration_ms: u64,
    pub planning_ms: u64,
    pub action_ms: u64,
    #[serde(default)]
    pub message: String,
    #[serde(default)]
    pub updated: f64,
}

fn folder() -> String {
    crate::config::paths().data_file(r"data\autonomous-tasks")
}

/// Last 20 task records; unfinished ones from an earlier run show as interrupted.
pub fn recent_jobs() -> Vec<Value> {
    let folder = folder();
    let mut files: Vec<(f64, String)> = fs::list_dir(&folder)
        .into_iter()
        .filter(|e| e.file && e.name.ends_with(".json"))
        .map(|e| fs::join(&folder, &e.name))
        .map(|p| (fs::stat(&p).map(|s| s.mtime).unwrap_or(0.0), p))
        .collect();
    files.sort_by(|a, b| b.0.total_cmp(&a.0));
    files
        .into_iter()
        .take(20)
        .filter_map(|(_, p)| fs::read_text(&p).and_then(|t| serde_json::from_str::<Value>(&t).ok()))
        .filter(|row| row.get("state").is_some() && row.get("id").is_some())
        .map(|mut row| {
            let active = ACTIVE_IDS.with(|a| a.borrow().contains(row["id"].as_str().unwrap_or("")));
            if matches!(row["state"].as_str(), Some("running" | "planning")) && !active {
                row["state"] = "interrupted".into();
                row["message"] = "The app stopped before this task finished. Review completed steps before restarting it.".into();
            }
            row
        })
        .collect()
}

#[derive(Default)]
pub struct Autonomous {
    /// Goal waiting for the user's clarification (empty when none).
    pub pending: RefCell<String>,
    planner: Rc<LocalPc>,
    queued: RefCell<VecDeque<(String, String, Rc<WebSocket>)>>,
    job: RefCell<Option<Job>>,
    task: RefCell<Option<AbortHandle>>,
    running: Rc<Cell<bool>>,
    notify: RefCell<Option<Rc<WebSocket>>>,
    observations: RefCell<Vec<Value>>,
    executed: RefCell<HashSet<String>>,
}

impl Autonomous {
    pub fn new() -> Rc<Self> {
        Rc::new(Self::default())
    }

    /// Starts `goal` in the background, or queues it behind the running task.
    pub fn start(self: &Rc<Self>, goal: &str, previous: &str, notify: Rc<WebSocket>) -> String {
        if self.running.get() {
            if ["stop", "cancel", "halt", "abbruch", "stop the task"].contains(&goal.to_lowercase().trim_matches(['.', '!', '?', ' '])) {
                self.queued.borrow_mut().clear();
                let me = self.clone();
                spawn_local(async move { me.cancel().await });
                return remember_english("Stopping the current task and clearing queued tasks.");
            }
            if self.queued.borrow().len() >= MAX_QUEUED_TASKS {
                return remember_english("The task queue is full. Wait for a task to finish or say stop.");
            }
            self.queued.borrow_mut().push_back((goal.to_string(), previous.to_string(), notify));
            return remember_english("I added that as the next task. I will start it after the current task finishes.");
        }
        let me = self.clone();
        let (goal, previous) = (goal.to_string(), previous.to_string());
        let running = self.running.clone();
        running.set(true);
        let (work, handle) = abortable(async move {
            let (mut goal, mut previous, mut notify) = (goal, previous, notify);
            loop {
                *me.notify.borrow_mut() = Some(notify);
                me.clone().run(&goal, &previous).await;
                me.publish();
                let Some(next) = me.queued.borrow_mut().pop_front() else { break };
                (goal, previous, notify) = next;
            }
        });
        let running_done = self.running.clone();
        let me = self.clone();
        spawn_local(async move {
            if work.await.is_err() {
                // Aborted: tell the client about the final state.
                me.publish();
            }
            running_done.set(false);
        });
        *self.task.borrow_mut() = Some(handle);
        String::new()
    }

    pub async fn cancel(&self) {
        self.queued.borrow_mut().clear();
        if let Some(handle) = self.task.borrow_mut().take() {
            handle.abort();
        }
        self.pending.borrow_mut().clear();
        let needs_input = self.job.borrow().as_ref().is_some_and(|j| j.state == "needs_input");
        if needs_input {
            self.update("cancelled", "Stopped. Completed actions were preserved.");
            self.save();
            self.publish();
        }
    }

    fn update(&self, state: &str, message: &str) {
        if let Some(job) = self.job.borrow_mut().as_mut() {
            job.state = state.into();
            job.message = message.into();
        }
    }

    fn with_job<T>(&self, f: impl FnOnce(&mut Job) -> T) -> Option<T> {
        self.job.borrow_mut().as_mut().map(f)
    }

    fn state(&self) -> String {
        self.job.borrow().as_ref().map(|j| j.state.clone()).unwrap_or_default()
    }

    fn message(&self) -> String {
        self.job.borrow().as_ref().map(|j| j.message.clone()).unwrap_or_default()
    }

    /// Durable history keeps progress only; content stays in the live task.
    fn save(&self) {
        let Some(mut saved) = self.with_job(|j| {
            j.updated = host::now_secs();
            j.clone()
        }) else {
            return;
        };
        saved.goal = "Task details are kept only in the active session.".into();
        saved.message = format!("Task {}.", saved.state.replace('_', " "));
        for row in &mut saved.steps {
            row.result = None;
            row.target = String::new();
        }
        let mut value = serde_json::to_value(&saved).unwrap_or_default();
        if let Some(steps) = value["steps"].as_array_mut() {
            for row in steps {
                if let Some(o) = row.as_object_mut() {
                    o.remove("target");
                }
            }
        }
        let folder = folder();
        let _ = fs::mkdirp(&folder);
        let _ = fs::write_text(&fs::join(&folder, &format!("{}.json", saved.id)), &serde_json::to_string_pretty(&value).unwrap_or_default());
    }

    fn publish(&self) {
        let Some(ws) = self.notify.borrow().clone() else { return };
        let Some(update) = self.with_job(|j| {
            json!({ "type": "task_update", "state": j.state, "message": j.message,
                "completed": j.steps.iter().filter(|r| r.state == "completed").count(), "total": j.steps.len(),
                "duration_ms": j.duration_ms, "planning_ms": j.planning_ms, "action_ms": j.action_ms })
        }) else {
            return;
        };
        ws.send_json(&update);
    }

    fn steps_len(&self) -> usize {
        self.with_job(|j| j.steps.len()).unwrap_or(0)
    }

    fn push_row(&self, step: &Value) -> usize {
        self.with_job(|j| {
            j.steps.push(Row { action: s(step, "action"), target: crate::util::take(&target_text(step), 300), state: "running".into(), ..Default::default() });
            j.steps.len() - 1
        })
        .unwrap_or(0)
    }

    fn finish_row(&self, index: usize, ok: bool, result: &str, attempts: u32, duration_ms: u64) {
        self.with_job(|j| {
            if let Some(row) = j.steps.get_mut(index) {
                row.state = if ok { "completed" } else { "needs_attention" }.into();
                row.result = Some(crate::util::take(result, 1000));
                row.attempts = Some(attempts);
                row.duration_ms = Some(duration_ms);
            }
            j.action_ms += duration_ms;
        });
    }

    /// Marks earlier failed rows of the same step as recovered.
    fn recover(&self, step: &Value, before: usize) {
        let (action, target) = (s(step, "action"), crate::util::take(&target_text(step), 300));
        self.with_job(|j| {
            for old in j.steps.iter_mut().take(before) {
                if old.action == action && old.target == target && old.state == "needs_attention" {
                    old.state = "recovered".into();
                }
            }
        });
    }

    fn prior(&self, step: &Value) -> Vec<Value> {
        self.observations.borrow().iter().filter(|o| o["step"] == *step).cloned().collect()
    }

    fn observe(&self, step: &Value, ok: bool, result: &str) {
        self.observations.borrow_mut().push(json!({ "step": step, "success": ok, "result": crate::util::take(result, 8000) }));
    }

    fn mark_recovered_observation(&self, step: &Value) {
        if let Some(o) = self.observations.borrow_mut().iter_mut().find(|o| o["step"] == *step) {
            o["recovered"] = true.into();
        }
    }

    fn repeated(&self) -> String {
        self.update("needs_attention", "A repeated action was prevented. Review the task history.");
        self.save();
        self.publish();
        remember_english(&self.message())
    }

    /// Finishes a terminal batch from the actual per-action results.
    fn finish_verified_batch(&self, count: usize) -> String {
        let observations: Vec<Value> = {
            let o = self.observations.borrow();
            o[o.len().saturating_sub(count)..].to_vec()
        };
        let rows_ok = self.with_job(|j| j.steps.len() >= count && j.steps[j.steps.len() - count..].iter().all(|r| r.state == "completed")).unwrap_or(false);
        if !rows_ok || observations.len() != count || observations.iter().any(|o| o["success"] != true) {
            self.update("needs_attention", "One or more requested actions did not complete. Review the task results.");
        } else {
            let parts: Vec<String> = observations
                .iter()
                .map(|item| {
                    let (action, target, result) = (s(&item["step"], "action"), target_text(&item["step"]), s(item, "result"));
                    match action.as_str() {
                        "read_file" => format!("{}: {result}", fs::file_name(&target)),
                        "list_folder" => format!("{target}: {result}"),
                        _ => result,
                    }
                })
                .collect();
            let message = crate::brain::tail_text(&parts.join(" "), 2000);
            self.update("completed", if message.is_empty() { "All requested actions completed." } else { &message });
        }
        self.save();
        self.publish();
        remember_english(&self.message())
    }

    async fn execute_one(&self, request: &str, previous: &str, step: &Value) -> (String, bool, u64, Option<Rc<LocalPc>>) {
        let reader = LocalPc::new();
        let started = now_ms();
        let result = reader.execute(request, previous, Some(vec![step.clone()])).await;
        let ok = reader.last_action_ok.get();
        let context = (s(step, "action") == "read_email").then_some(reader);
        (result, ok, (now_ms() - started) as u64, context)
    }

    /// Runs independent reads or one calendar action alongside an explicit open.
    async fn independent_local_steps(&self, request: &str, previous: &str, steps: &[Value]) -> Option<String> {
        let actions: Vec<String> = steps.iter().map(|st| s(st, "action")).collect();
        let work = |a: &str| is_read(a) || a == "calendar_task";
        let opens: Vec<&Value> = steps.iter().filter(|st| is_open(&s(st, "action"))).collect();
        if steps.len() < 2 || self.steps_len() + steps.len() > 12 || !actions.iter().any(|a| work(a)) || actions.iter().any(|a| !work(a) && !is_open(a)) || opens.len() > 1 {
            return None;
        }
        let mail_reads: Vec<&Value> = steps.iter().filter(|st| st["action"] == "read_email").collect();
        if !mail_reads.is_empty() {
            // One mail read may overlap one unrelated launch, never its own app or page.
            if mail_reads.len() != 1 || steps.len() != 2 || opens.len() != 1 {
                return None;
            }
            let provider = s(mail_reads[0], "target").trim().to_lowercase();
            let opening = opens[0];
            let target = target_text(opening).trim().to_string();
            let outlook = provider == "outlook" || provider == "microsoft outlook";
            let mut same = outlook && opening["action"] == "open_app" && ["outlook", "microsoft outlook"].contains(&target.to_lowercase().as_str());
            if opening["action"] == "open_url" {
                let host = crate::websites::validate_url(&target).map(|(_, h)| h.to_lowercase()).unwrap_or_default();
                same = same
                    || ((provider == "gmail" || provider == "google mail") && (host == "mail.google.com" || host == "gmail.com"))
                    || (outlook && ["outlook.office.com", "outlook.live.com", "outlook.com"].contains(&host.as_str()));
            }
            if same {
                return None;
            }
        }
        let calendar_count = actions.iter().filter(|a| *a == "calendar_task").count();
        if calendar_count > 0 && (calendar_count != 1 || actions.iter().any(|a| is_read(a))) {
            return None;
        }
        let mut prepared: Vec<(Value, bool)> = Vec::new();
        let mut batch: HashSet<String> = HashSet::new();
        for step in steps {
            let fingerprint = step.to_string();
            let prior = self.prior(step);
            let retry_read = is_read(&s(step, "action")) && prior.len() == 1 && prior[0]["success"] != true;
            if !batch.insert(fingerprint.clone()) || (self.executed.borrow().contains(&fingerprint) && !retry_read) {
                return Some(self.repeated());
            }
            prepared.push((step.clone(), retry_read));
        }
        let mut rows: Vec<(Value, usize, bool)> = Vec::new();
        for (step, retry_read) in prepared {
            self.executed.borrow_mut().insert(step.to_string());
            let index = self.push_row(&step);
            rows.push((step, index, retry_read));
        }
        let count = |f: &dyn Fn(&str) -> bool| rows.iter().filter(|(st, _, _)| f(&s(st, "action"))).count();
        let files = count(&|a| a == "read_file" || a == "list_folder");
        let mut activities = Vec::new();
        if files > 0 {
            activities.push(format!("Reading {files} independent files and folders"));
        }
        if count(&|a| a == "read_email") > 0 {
            activities.push("Reading email".to_string());
        }
        if count(&|a| a == "calendar_task") > 0 {
            activities.push("Checking the requested calendar action".to_string());
        }
        let mut message = activities.join(" and ");
        if let Some((st, _, _)) = rows.iter().find(|(st, _, _)| is_open(&s(st, "action"))) {
            message += &format!("{}opening {}", if message.is_empty() { "" } else { " while " }, target_text(st));
        }
        self.update("running", &format!("{message}."));
        self.save();
        self.publish();
        let mut outcomes = join_all(rows.iter().map(|(st, _, _)| self.execute_one(request, previous, st))).await;
        let retry: Vec<usize> = rows
            .iter()
            .zip(&outcomes)
            .enumerate()
            .filter(|(_, ((st, _, retry_read), (result, ok, _, _)))| !ok && !retry_read && is_read(&s(st, "action")) && transient_read_failure(result))
            .map(|(i, _)| i)
            .collect();
        if !retry.is_empty() {
            let again = join_all(retry.iter().map(|i| self.execute_one(request, previous, &rows[*i].0))).await;
            for (i, (result, ok, ms, context)) in retry.iter().zip(again) {
                let (first, _, first_ms, _) = &outcomes[*i];
                outcomes[*i] = (if ok { result } else { format!("{first} Retry: {result}") }, ok, first_ms + ms, context);
            }
        }
        for (i, ((step, index, retry_read), (result, ok, ms, context))) in rows.iter().zip(outcomes).enumerate() {
            self.finish_row(*index, ok, &result, if *retry_read || retry.contains(&i) { 2 } else { 1 }, ms);
            if let Some(reader) = context {
                self.planner.mail_context.copy_from(&reader.mail_context);
            }
            if *retry_read && ok {
                self.mark_recovered_observation(step);
                self.recover(step, *index - (i));
            }
            self.observe(step, ok, &result);
        }
        self.save();
        self.publish();
        Some(String::new())
    }

    /// Launches independent app-only batches concurrently, never with a website.
    async fn independent_app_opens(&self, request: &str, previous: &str, steps: &[Value]) -> Option<String> {
        if steps.len() < 2 || self.steps_len() + steps.len() > 12 || steps.iter().any(|st| st["action"] != "open_app" || target_text(st).trim().is_empty()) {
            return None;
        }
        let mut fingerprints = HashSet::new();
        let mut targets = HashSet::new();
        for step in steps {
            let fingerprint = step.to_string();
            if !fingerprints.insert(fingerprint.clone()) || self.executed.borrow().contains(&fingerprint) || !targets.insert(target_text(step).trim().to_lowercase()) {
                return Some(self.repeated());
            }
        }
        let rows: Vec<(Value, usize)> = steps
            .iter()
            .map(|st| {
                self.executed.borrow_mut().insert(st.to_string());
                (st.clone(), self.push_row(st))
            })
            .collect();
        self.update("running", &format!("Opening {} independent apps.", rows.len()));
        self.save();
        self.publish();
        let outcomes = join_all(rows.iter().map(|(st, _)| self.execute_one(request, previous, st))).await;
        for ((step, index), (result, ok, ms, _)) in rows.iter().zip(outcomes) {
            self.finish_row(*index, ok, &result, 1, ms);
            self.observe(step, ok, &result);
        }
        self.save();
        self.publish();
        Some(String::new())
    }

    async fn run(self: Rc<Self>, goal: &str, previous: &str) -> String {
        let started = now_ms();
        let resuming = !self.pending.borrow().is_empty() && self.state() == "needs_input";
        let request = if resuming { format!("{}\nUser clarification: {goal}", self.pending.borrow()) } else { goal.to_string() };
        self.pending.borrow_mut().clear();
        if resuming {
            self.with_job(|j| {
                j.goal = crate::util::take(&request, 2000);
                j.state = "planning".into();
            });
        } else {
            self.observations.borrow_mut().clear();
            self.executed.borrow_mut().clear();
            *self.job.borrow_mut() = Some(Job {
                id: crate::util::uuid_hex(),
                goal: crate::util::take(&request, 2000),
                state: "planning".into(),
                started: host::now_secs(),
                ..Default::default()
            });
        }
        let id = self.with_job(|j| j.id.clone()).unwrap_or_default();
        ACTIVE_IDS.with(|a| a.borrow_mut().insert(id.clone()));
        self.save();
        let email_task = is_email_request(&normalize_request(&request));
        // Stop drops this future; the guard records the cancellation.
        let mut guard = RunGuard { auto: self.clone(), started, id, finished: false };
        let result = with_timeout(TASK_TIMEOUT_MS, self.rounds(&request, previous)).await;
        guard.finished = true;
        match result {
            Ok(reply) => reply,
            Err(_) => {
                self.interrupt_running();
                self.update("needs_attention", &format!("Task exceeded its {}-second time limit.", TASK_TIMEOUT_MS as u64 / 1000));
                remember_english(if email_task {
                    "The email task took too long. Check the draft or Sent folder and task history before retrying; I will not repeat a send automatically."
                } else {
                    "The task reached its time limit. Check task status for completed steps before retrying."
                })
            }
        }
    }

    fn interrupt_running(&self) {
        self.with_job(|j| {
            for row in &mut j.steps {
                if row.state == "running" {
                    row.state = "interrupted".into();
                }
            }
        });
    }

    async fn rounds(&self, request: &str, previous: &str) -> String {
        match self.rounds_inner(request, previous).await {
            Ok(reply) => reply,
            Err(_) => {
                self.interrupt_running();
                self.update("needs_attention", "Planning or execution failed; completed steps will not be repeated automatically.");
                remember_english("I could not complete that task. Check the OpenAI connection and the task history in Settings.")
            }
        }
    }

    async fn rounds_inner(&self, request: &str, previous: &str) -> Result<String, String> {
        while self.with_job(|j| j.rounds < 8 && j.steps.len() < 12).unwrap_or(false) {
            self.update("planning", "Evaluating the next steps.");
            self.with_job(|j| j.rounds += 1);
            self.save();
            self.publish();
            let planning_started = now_ms();
            let observations = self.observations.borrow().clone();
            let phase = self.planner.plan_next(request, previous, &observations).await;
            self.with_job(|j| j.planning_ms += (now_ms() - planning_started) as u64);
            let phase = phase?;
            let steps: Vec<Value> = phase["steps"].as_array().cloned().unwrap_or_default();
            let terminal = phase["terminal"] == true;
            if phase["complete"] == true {
                // A model may not erase unresolved failures by declaring success.
                if self.with_job(|j| j.steps.iter().any(|r| r.state == "needs_attention")).unwrap_or(false) {
                    self.update("needs_attention", "Some actions failed. Review the task history.");
                } else {
                    let m = s(&phase, "message");
                    self.update("completed", if m.is_empty() { "All requested supported actions completed." } else { &m });
                }
                return Ok(remember_english(&self.message()));
            }
            let terminal_observation = terminal && !steps.is_empty() && steps.iter().all(|st| is_read(&s(st, "action")) || is_open(&s(st, "action")));
            if self.independent_app_opens(request, previous, &steps).await.is_some() {
                if self.state() == "needs_attention" {
                    return Ok(remember_english(&self.message()));
                }
                if terminal {
                    return Ok(self.finish_verified_batch(steps.len()));
                }
                continue;
            }
            let terminal_parallel_reads = terminal_observation && steps.len() > 1 && steps.iter().any(|st| is_read(&s(st, "action")));
            if self.independent_local_steps(request, previous, &steps).await.is_some() {
                if self.state() == "needs_attention" {
                    return Ok(remember_english(&self.message()));
                }
                if terminal_parallel_reads {
                    return Ok(self.finish_verified_batch(steps.len()));
                }
                if terminal {
                    let latest_ok = {
                        let o = self.observations.borrow();
                        o.len() >= steps.len() && o[o.len() - steps.len()..].iter().all(|x| x["success"] == true)
                    };
                    if latest_ok {
                        return Ok(self.finish_verified_batch(steps.len()));
                    }
                }
                continue;
            }
            let mut finished_all = true;
            for (step_index, step) in steps.iter().enumerate() {
                let action = s(step, "action");
                if action == "ask" {
                    *self.pending.borrow_mut() = request.to_string();
                    self.update("needs_input", &s(step, "content"));
                    return Ok(remember_english(&s(step, "content")));
                }
                if self.steps_len() >= 12 {
                    finished_all = false;
                    break;
                }
                let fingerprint = step.to_string();
                let prior = self.prior(step);
                let retry_read = is_read(&action) && prior.len() == 1 && prior[0]["success"] != true;
                if self.executed.borrow().contains(&fingerprint) && !retry_read {
                    self.update("needs_attention", "A repeated action was prevented. Review the task history.");
                    return Ok(remember_english(&self.message()));
                }
                self.executed.borrow_mut().insert(fingerprint.clone());
                let index = self.push_row(step);
                self.update("running", &format!("Step {}: {}", index + 1, action.replace('_', " ")));
                self.save();
                self.publish();
                let action_started = now_ms();
                let (mut result, mut ok);
                if action == "codex_prompt" {
                    self.with_job(|j| j.message = "Codex is working. I will evaluate its report before continuing.".into());
                    self.publish();
                    let cancel: Cancel = Rc::new(Cell::new(false));
                    let _stop = CancelOnDrop(cancel.clone());
                    let project = target_text(step);
                    match pc_control::run_code(&s(step, "content"), if project.is_empty() { None } else { Some(project.as_str()) }, &cancel).await {
                        Ok(report) => {
                            result = report;
                            ok = true;
                        }
                        Err(e) => {
                            result = format!("Coding task did not complete: {}", crate::util::take(&e, 400));
                            ok = false;
                        }
                    }
                } else {
                    result = self.planner.execute(request, previous, Some(vec![step.clone()])).await;
                    ok = self.planner.last_action_ok.get();
                    if self.planner.needs_input.get() {
                        // Validation asks before opening or editing a composer.
                        self.executed.borrow_mut().remove(&fingerprint);
                        let ms = (now_ms() - action_started) as u64;
                        self.with_job(|j| {
                            if let Some(row) = j.steps.get_mut(index) {
                                row.state = "awaiting_input".into();
                                row.result = Some(crate::util::take(&result, 1000));
                                row.attempts = Some(0);
                                row.duration_ms = Some(ms);
                            }
                            j.action_ms += ms;
                        });
                        *self.pending.borrow_mut() = request.to_string();
                        self.planner.pending.borrow_mut().clear();
                        self.update("needs_input", &result);
                        return Ok(result);
                    }
                }
                let mut duration = (now_ms() - action_started) as u64;
                let mut attempts = if retry_read { 2 } else { 1 };
                if !ok && terminal_observation && !retry_read && is_read(&action) && transient_read_failure(&result) {
                    let first = result.clone();
                    attempts = 2;
                    self.with_job(|j| {
                        if let Some(row) = j.steps.get_mut(index) {
                            row.state = "retrying".into();
                            row.attempts = Some(2);
                            row.result = Some("A transient read error occurred; retrying once.".into());
                        }
                    });
                    self.save();
                    self.publish();
                    let again = now_ms();
                    result = self.planner.execute(request, previous, Some(vec![step.clone()])).await;
                    ok = self.planner.last_action_ok.get();
                    duration += (now_ms() - again) as u64;
                    if !ok {
                        result = format!("{first} Retry: {result}");
                    }
                }
                self.finish_row(index, ok, &result, attempts, duration);
                if retry_read && ok {
                    self.mark_recovered_observation(step);
                    self.recover(step, index);
                }
                self.observe(step, ok, &result);
                self.save();
                self.publish();
                let remaining_opens = {
                    let rest = &steps[step_index + 1..];
                    !rest.is_empty() && rest.iter().all(|n| is_open(&s(n, "action")))
                };
                if !ok {
                    // Explicitly planned launches are independent of a failed action.
                    if remaining_opens {
                        continue;
                    }
                    if !is_read(&action) && !is_open(&action) {
                        self.update("needs_attention", &crate::util::take(&result, 1000));
                        return Ok(result);
                    }
                    if terminal_observation {
                        return Ok(self.finish_verified_batch(steps.len()));
                    }
                    // The next round sees the real error; no blind retry.
                    finished_all = false;
                    break;
                }
                if action == "read_email" {
                    if remaining_opens {
                        continue;
                    }
                    if terminal {
                        return Ok(self.finish_verified_batch(steps.len()));
                    }
                    finished_all = false;
                    break;
                }
                if action == "codex_prompt" {
                    // The report must be evaluated before dependent follow-up.
                    finished_all = false;
                    break;
                }
            }
            if finished_all && terminal {
                if self.with_job(|j| j.steps.iter().any(|r| r.state == "needs_attention")).unwrap_or(false) {
                    self.update("needs_attention", "Some actions failed. Review the task history.");
                } else {
                    let joined: Vec<String> = self.observations.borrow().iter().map(|o| s(o, "result")).collect();
                    self.update("completed", &crate::brain::tail_text(&joined.join(" "), 2000));
                }
                return Ok(remember_english(&self.message()));
            }
        }
        self.update("needs_attention", "Task reached its limit of 12 actions or 8 planning rounds. Completed actions were preserved.");
        Ok(remember_english(&self.message()))
    }

    fn progress(&self) -> (usize, usize) {
        self.with_job(|j| {
            let rows: Vec<&Row> = j.steps.iter().filter(|r| r.state != "recovered").collect();
            (rows.iter().filter(|r| r.state == "completed").count(), rows.len())
        })
        .unwrap_or((0, 0))
    }

    pub fn status(&self) -> String {
        if self.job.borrow().is_none() {
            return remember_english("No autonomous task has been started in this session.");
        }
        let (completed, total) = self.progress();
        let mut result = format!("Task status: {}. {completed} of {total} steps completed.", self.state().replace('_', " "));
        let message = self.message();
        if !message.is_empty() {
            result += &format!(" {message}");
        }
        remember_english(&result)
    }
}

/// Records a stopped task (its future was dropped) and the run's duration.
struct RunGuard {
    auto: Rc<Autonomous>,
    started: f64,
    id: String,
    finished: bool,
}

impl Drop for RunGuard {
    fn drop(&mut self) {
        if !self.finished {
            self.auto.pending.borrow_mut().clear();
            self.auto.update("cancelled", "Stopped. Completed actions were not undone.");
            self.auto.interrupt_running();
        }
        let elapsed = (now_ms() - self.started) as u64;
        self.auto.with_job(|j| j.duration_ms += elapsed);
        self.auto.save();
        ACTIVE_IDS.with(|a| a.borrow_mut().remove(&self.id));
    }
}

struct CancelOnDrop(Cancel);
impl Drop for CancelOnDrop {
    fn drop(&mut self) {
        self.0.set(true);
    }
}
