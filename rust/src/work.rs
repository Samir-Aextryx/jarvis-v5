//! Codex sessions tied to a project directory (work mode and dispatches),
//! and the casual-question check that keeps small talk out of Codex.

use crate::host::fs;
use crate::pc_control::{self, Cancel, STOPPED};
use std::cell::{Cell, RefCell};
use std::rc::Rc;

#[derive(Default)]
pub struct WorkSession {
    active: Cell<bool>,
    working_dir: RefCell<Option<String>>,
    project_name: RefCell<Option<String>>,
    pub message_count: Cell<u32>,
    status: RefCell<&'static str>, // idle, working, done, error, cancelled
    cancel: RefCell<Cancel>,
}

impl WorkSession {
    pub fn new() -> Rc<Self> {
        Rc::new(Self { status: RefCell::new("idle"), ..Default::default() })
    }
    pub fn active(&self) -> bool {
        self.active.get()
    }
    pub fn status(&self) -> &'static str {
        *self.status.borrow()
    }
    pub fn start(&self, working_dir: &str, project_name: Option<&str>) {
        let name = project_name.map(str::to_string).unwrap_or_else(|| fs::file_name(working_dir).to_string());
        crate::info!("Work mode started: {name} ({working_dir})");
        *self.working_dir.borrow_mut() = Some(working_dir.to_string());
        *self.project_name.borrow_mut() = Some(name);
        self.active.set(true);
        self.message_count.set(0);
        *self.status.borrow_mut() = "idle";
        *self.cancel.borrow_mut() = Rc::new(Cell::new(false));
    }

    /// Sends the task to Codex in the project folder and waits for its report.
    pub async fn send(&self, text: &str) -> String {
        // A previous Stop may have set the flag; a new task starts fresh.
        let cancel: Cancel = Rc::new(Cell::new(false));
        *self.cancel.borrow_mut() = cancel.clone();
        let id = pc_control::new_job("code");
        pc_control::register_cancel(&id, cancel.clone());
        *self.status.borrow_mut() = "working";
        let dir = self.working_dir.borrow().clone();
        // Dropping this future (turn interrupted) must stop Codex too.
        let guard = CancelOnDrop(cancel.clone());
        let result = pc_control::code(&id, text, dir.as_deref(), &cancel).await;
        std::mem::forget(guard);
        let message = if cancel.get() {
            pc_control::set_state(&id, "cancelled", Some(STOPPED));
            *self.status.borrow_mut() = "cancelled";
            STOPPED.to_string()
        } else if result.is_ok() {
            pc_control::set_state(&id, "done", None);
            self.message_count.set(self.message_count.get() + 1);
            *self.status.borrow_mut() = "done";
            pc_control::job_message(&id).unwrap_or_else(|| "Codex finished the task.".into())
        } else {
            let m = "Hit a problem: Codex did not finish the task. Check the task in Codex and your sign-in.";
            pc_control::set_state(&id, "error", Some(m));
            *self.status.borrow_mut() = "error";
            m.to_string()
        };
        pc_control::drop_cancel(&id);
        pc_control::persist(&id);
        message
    }

    /// Stops the current Codex run but keeps the project session.
    pub fn cancel(&self) -> bool {
        if self.status() != "working" {
            return false;
        }
        self.cancel.borrow().set(true);
        true
    }

    /// Ends the session and stops any Codex process it owns.
    pub fn stop(&self) {
        self.cancel.borrow().set(true);
        let project = self.project_name.borrow_mut().take();
        self.active.set(false);
        *self.working_dir.borrow_mut() = None;
        self.message_count.set(0);
        if self.status() != "cancelled" {
            *self.status.borrow_mut() = "idle";
        }
        crate::info!("Work mode ended for {}", project.unwrap_or_else(|| "None".into()));
    }
}

/// Marks the job cancelled when its future is dropped before finishing.
struct CancelOnDrop(Cancel);
impl Drop for CancelOnDrop {
    fn drop(&mut self) {
        self.0.set(true);
    }
}

