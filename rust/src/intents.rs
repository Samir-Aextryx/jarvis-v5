//! Deterministic request parsing: unambiguous commands need neither
//! inference nor a network connection.

use crate::util::collapse_ws;
use serde_json::{Value, json};

pub fn normalize_request(text: &str) -> String {
    let mut text = text.trim().to_string();
    for _ in 0..4 {
        text = crate::re!(r"(?i)^(?:(?:hey\s+)?jarvis[, ]+|please\s+|bitte\s+|can you\s+|could you\s+|kannst du\s+)")
            .replace(text.trim(), "")
            .to_string();
    }
    text
}

pub fn step(action: &str, target: &str, content: &str) -> Value {
    json!({ "action": action, "target": target, "content": content, "recipient": "", "subject": "" })
}

pub fn ask(content: &str) -> Vec<Value> {
    vec![step("ask", "", content)]
}

const MESSAGE_BODY: &str = r"\s+(?:saying|with\s+(?:the\s+)?(?:text|body)|message\s+is|text:|mit\s+(?:dem\s+)?(?:text|inhalt)|dass|:)\s+";
const MESSAGE_APP: &str = r"(?:(?:microsoft\s+)?teams|snapchat|whatsapp)";

fn unsupported_action(phrase: &str) -> bool {
    crate::re!(
        r"(?i)^(?:delete|remove|erase|uninstall|install|upload|download|attach|buy|purchase|pay|checkout|publish|post|cancel|lösche|loesche|löschen|lösch|loesch|entferne|entfernen|entfern|deinstalliere|installiere|lade\s+hoch|lade\s+herunter|hänge\s+an|kaufe|bezahle|veröffentliche|veroeffentliche|poste|kündige|kuendige)\b"
    )
    .is_match(phrase)
        || crate::re!(
            r"(?i)^(?:change|reset|set|update|ändere|aendere|setze|aktualisiere)\s+(?:(?:my|the|your|mein(?:e|en|em|er)?|dein(?:e|en|em|er)?|das|den|die)\s+)?(?:password|passcode|account|security|privacy|permission|payment|billing|recovery|two[ -]?factor|2fa|passwort|konto|sicherheit|datenschutz|berechtigung|zwei[ -]?faktor)\b"
        )
        .is_match(phrase)
}

/// Fail fast for UI operations this desktop agent is explicitly not trained to do.
pub fn unsupported_action_plan(text: &str) -> Option<Vec<Value>> {
    let text = normalize_request(text);
    // ChatGPT/Codex prompts are the user's requested content, not actions.
    if crate::re!(r"(?i)^(?:(?:open|launch|öffne|oeffne)\s+)?(?:chat\s*gpt|claude|codex)\b.*\b(?:prompt|tell|ask|sage|schreibe)\b").is_match(&text) {
        return None;
    }
    let body_start = crate::re!(r"(?i)\b(?:saying|message\s+is|with\s+(?:the\s+)?(?:text|body|content)|body:|content:|text:|mit\s+(?:dem\s+)?(?:text|inhalt)|und\s+(?:text|inhalt)|dass)\b");
    let command = body_start.splitn(&text, 2).next().unwrap_or("").trim().to_string();
    let command = crate::re!(r"(?i)^(?:(?:i\s+(?:want|need|would\s+like)\s+you\s+to)|(?:ich\s+(?:möchte|moechte|will)\s+(?:dass\s+du\s+)?)|(?:please|bitte|could\s+you|would\s+you))\s+")
        .replace(&command, "")
        .to_string();
    for fragment in crate::re!(r"(?i)\s+(?:and\s+then|then|and|und\s+dann|und|danach)\s+").split(&command) {
        let phrase = fragment.trim_matches([' ', ',', '.', '!', '?']);
        if crate::re!(r"(?i)^(?:don't|do\s+not|never|not|without|nicht|niemals|kein(?:e|en|er|es)?)\b").is_match(phrase) {
            continue;
        }
        if crate::re!(r"(?i)\b(?:calendar|appointment|meeting|event|termin|kalender|besprechung|ereignis)\b").is_match(phrase)
            && crate::re!(r"(?i)^(?:delete|remove|cancel|lösche|loesche|entferne|storniere|absage)\b").is_match(phrase)
        {
            continue;
        }
        if unsupported_action(phrase) {
            return Some(ask("I can't do that yet because I haven't been trained for that action."));
        }
    }
    None
}

#[derive(Debug, Clone)]
pub struct MessageParts {
    pub app: String,
    pub recipient: String,
    pub content: String,
    pub send_requested: bool,
    pub explicit_app: bool,
}

fn app_label(name: &str) -> String {
    let name = crate::re!(r"(?i)^microsoft\s+").replace(name, "").to_lowercase();
    match name.as_str() {
        "snapchat" => "Snapchat",
        "whatsapp" => "WhatsApp",
        _ => "Teams",
    }
    .to_string()
}

/// One explicitly addressed message, separating command from literal text.
pub fn message_request_parts(text: &str) -> Option<MessageParts> {
    let mut text = normalize_request(text).trim().to_string();
    let mut app = "Teams".to_string();
    let mut explicit_app = false;
    let opening = regex::Regex::new(&format!(r"(?is)^(?:open|launch|öffne|oeffne)\s+({MESSAGE_APP})\b(?:\s+(?:and|then|und)\s+)?")).ok()?;
    if let Some(m) = opening.captures(&text) {
        app = app_label(&m[1]);
        explicit_app = true;
        text = text[m.get(0)?.end()..].to_string();
    }
    let action = crate::re!(r"(?is)^(send|sende|schick(?:e)?|versende|write|draft|compose|schreibe|schreib|verfasse)\s+(?:(?:a|an|eine|einen)\s+)?").captures(&text)?;
    let verb = action[1].to_lowercase();
    let mut rest = text[action.get(0)?.end()..].to_string();
    let prefix = regex::Regex::new(&format!(r"(?is)^({MESSAGE_APP})\s+(?:message|messag|text|nachricht)\s+(?:to|an)\s+")).ok()?;
    if let Some(m) = prefix.captures(&rest) {
        app = app_label(&m[1]);
        explicit_app = true;
        rest = rest[m.get(0)?.end()..].to_string();
    } else {
        let noun = crate::re!(r"(?is)^(?:message|messag|text|nachricht)\s+(?:to|an)\s+").find(&rest)?;
        rest = rest[noun.end()..].to_string();
    }
    let body_re = regex::Regex::new(&format!("(?i){MESSAGE_BODY}")).ok()?;
    let body_match = body_re.find(&rest);
    let mut recipient = match body_match {
        Some(m) => rest[..m.start()].trim().to_string(),
        None => rest.trim().trim_end_matches(['.', '!', '?', ' ']).to_string(),
    };
    let body = body_match.map(|m| rest[m.end()..].trim().to_string()).unwrap_or_default();
    let suffix = regex::Regex::new(&format!(r"(?is)\s+(?:on|in|via|über)\s+({MESSAGE_APP})\s*$")).ok()?;
    if let Some(m) = suffix.captures(&recipient.clone()) {
        app = app_label(&m[1]);
        explicit_app = true;
        recipient = recipient[..m.get(0)?.start()].trim().to_string();
    }
    if recipient.is_empty() || recipient.chars().count() > 80 || !crate::re!(r"^[\w .@+-]+$").is_match(&recipient) {
        return None;
    }
    if body.chars().count() > 12000 || body.chars().any(|c| (c as u32) < 32 && !"\n\r\t".contains(c)) {
        return None;
    }
    Some(MessageParts {
        app,
        recipient,
        content: body,
        send_requested: ["send", "sende", "schick", "schicke", "versende"].contains(&verb.as_str()),
        explicit_app,
    })
}

/// An exact one-recipient message without asking a model to rewrite it.
pub fn direct_message_plan(text: &str) -> Option<Value> {
    let parts = message_request_parts(text)?;
    if parts.content.is_empty() {
        return None;
    }
    Some(json!({ "action": "draft_message", "target": parts.app, "recipient": parts.recipient, "content": parts.content, "subject": "" }))
}

/// Only a send verb in the command (before message text) can authorize submission.
pub fn message_send_requested(text: &str) -> bool {
    message_request_parts(text).is_some_and(|p| p.send_requested)
}

/// A reply to a missing-message question becomes a literal draft without an LLM.
pub fn message_clarification_plan(text: &str) -> Option<Vec<Value>> {
    let m = crate::re!(r"(?is)^(.*?)\nUser clarification:\s*(.+)$").captures(text.trim())?;
    let (original, content) = (m[1].trim(), m[2].trim());
    let parts = message_request_parts(original)?;
    if !parts.explicit_app || !parts.content.is_empty() || content.is_empty() {
        return None;
    }
    if crate::re!(r"(?i)^(?:send|send it|send the message|sende|sende es|sende sie|abschicken)$").is_match(content) {
        return Some(ask(&format!("What should I say to {}?", parts.recipient)));
    }
    Some(vec![json!({ "action": "draft_message", "target": parts.app, "recipient": parts.recipient, "content": content, "subject": "" })])
}

fn explicit_file_read_batch(text: &str) -> Option<Vec<Value>> {
    let command = crate::re!(r"(?is)^(?:read|lies|lese)\s+(?:(?:both|these|the|die|diese)\s+)?(?:files?|dateien)?\s*(.+)$").captures(text.trim())?;
    let remainder = command.get(1)?.as_str();
    let paths = crate::re!(r#""(?P<double>[^"\r\n]+)"|'(?P<single>[^'\r\n]+)'|(?P<plain>(?:[A-Za-z]:[\\/]|\\\\)[^\s,;]+)"#);
    let matches: Vec<regex::Captures> = paths.captures_iter(remainder).collect();
    if !(2..=4).contains(&matches.len()) || !remainder[..matches[0].get(0)?.start()].trim().is_empty() {
        return None;
    }
    let separators = crate::re!(r"(?i)^\s*(?:and(?:\s+then)?|then|und(?:\s+(?:dann|danach))?|danach|,)\s*$");
    let mut seen = std::collections::HashSet::new();
    let mut targets = Vec::new();
    for (index, m) in matches.iter().enumerate() {
        let plain = m.name("plain");
        let raw = m.name("double").or(m.name("single")).or(plain)?.as_str();
        let target = if plain.is_some() { raw.trim_end_matches(['.', '!', '?']) } else { raw };
        let ext = target.rsplit_once('.').map(|(_, e)| e.to_lowercase()).unwrap_or_default();
        if !crate::re!(r"^[A-Za-z]:[\\/]").is_match(target)
            || target.starts_with("\\\\")
            || !["txt", "md", "csv", "py", "js", "ts", "html", "css"].contains(&ext.as_str())
        {
            return None;
        }
        if !seen.insert(target.replace('/', "\\").to_lowercase()) {
            return None;
        }
        targets.push(step("read_file", target, ""));
        if index > 0 {
            let gap = &remainder[matches[index - 1].get(0)?.end()..m.get(0)?.start()];
            if !separators.is_match(gap) {
                return None;
            }
        }
    }
    if !remainder[matches.last()?.get(0)?.end()..].trim().trim_matches(['.', '!', '?']).is_empty() {
        return None;
    }
    Some(targets)
}

pub fn fast_plan(text: &str) -> Option<Vec<Value>> {
    let text = normalize_request(text);
    if let Some(plan) = unsupported_action_plan(&text) {
        return Some(plan);
    }
    if let Some(plan) = message_clarification_plan(&text) {
        return Some(plan);
    }
    if let Some(message) = direct_message_plan(&text) {
        return Some(vec![message]);
    }
    if let Some(m) = crate::re!(r"(?i)^(?:open|launch|öffne|oeffne)\s+(snapchat|whatsapp|telegram|teams)\s+(?:(?:and|then|und)\s+)?(?:write|send|schreibe|schreib|sende)\s+(?:(?:a|eine)\s+)?(?:message|messag|text|nachricht)\s+(?:to|an)\s+([\w -]{1,60})[.!?]*$").captures(&text) {
        return Some(ask(&format!("What would you like to tell {}?", m[2].trim())));
    }
    let ai_app = r"(?:chat\s*gpt|chatgpt|claude(?:\s+code)?)";
    let verb = r"(?:prompt|prompte|tell|ask|sage?|frage?|schreibe?)";
    let link = r"(?:to\s+|that\s+|dass\s+|(?:er|sie|es)\s+soll\s+)?";
    let patterns = [
        format!(r"(?is)^(?:open|launch|öffne|oeffne)\s+(?P<app>{ai_app})[,:]?\s+(?:(?:and|then|und)\s+)?{verb}\s+(?:(?:it|him|her|ihm|ihr)\s+)?{link}(?P<content>.+)$"),
        format!(r"(?is)^{verb}\s+(?P<app>{ai_app})[,:]?\s+{link}(?P<content>.+)$"),
    ];
    for pattern in &patterns {
        let Ok(re) = regex::Regex::new(pattern) else { continue };
        if let Some(m) = re.captures(&text) {
            let app = collapse_ws(&m["app"].to_lowercase());
            let content = m["content"].trim().trim_matches([' ', ',']).to_string();
            if !content.is_empty() && app.starts_with("claude") {
                let target = if app.ends_with("code") { "Claude Code" } else { "Claude" };
                return Some(vec![step("claude_prompt", target, &content)]);
            }
            if !content.is_empty() {
                return Some(vec![step("chatgpt_prompt", "", &content)]);
            }
        }
    }
    if let Some(m) = crate::re!(r"(?is)^(?:save|create|write)\s+(?:a\s+)?file\s+(?:called|named)\s+(.+?)\s+(?:to|on)\s+(?:the\s+)?(?:desktop|desktp)\s+with\s+(?:the\s+)?(?:content|text)\s+(.+)$").captures(&text) {
        let filename = crate::re!(r"(?i)\s+dot\s+").replace_all(m[1].trim().trim_matches('"'), ".").to_string();
        return Some(vec![step("write_desktop", &filename, &m[2])]);
    }
    if crate::re!(r"(?i)^(?:save|create|write)\s+(?:a\s+)?file\s+(?:to|on)\s+(?:the\s+)?(?:desktop|desktp)[.!?]*$").is_match(&text) {
        return Some(ask("What filename should I use, and what should the file contain?"));
    }
    if let Some(batch) = explicit_file_read_batch(&text) {
        return Some(batch);
    }
    let read = crate::re!(r"(?is)^(?:read|lies|lese)\s+(?:(?:me|mir)\s+)?(?:(?:the|die|das|eine?)\s+)?(?:file|datei)\s+(.+)$").captures(&text);
    let list = [
        crate::re!(r"(?is)^(?:list|liste)\s+(?:(?:the|den)\s+)?(?:folder|directory|ordner)\s+(.+)$"),
        crate::re!(r"(?is)^(?:show|display|list)\s+(?:(?:me|the)\s+)*(?:contents|files)\s+(?:of|in)\s+(?:(?:the|folder)\s+)?(.+)$"),
        crate::re!(r"(?is)^(?:zeige|liste)\s+(?:(?:den|die)\s+)?(?:inhalt\s+von|dateien\s+in)\s+(.+)$"),
    ]
    .iter()
    .find_map(|re| re.captures(&text));
    let local = read.map(|m| ("read_file", m[1].to_string())).or(list.map(|m| ("list_folder", m[1].to_string())));
    if let Some((action, spoken)) = local {
        let mut target = spoken.trim().to_string();
        if target.ends_with(['.', '!', '?']) {
            target.pop();
            target = target.trim_end().to_string();
        }
        let target = target.trim_matches('"').trim().to_string();
        if target.is_empty()
            || crate::re!(r"(?i)\s+(?:and|then|und|danach)\s+(?:open|read|list|write|save|send|schreibe|öffne|lies|liste|zeige)\b").is_match(&target)
        {
            return None;
        }
        return Some(vec![step(action, &target, "")]);
    }
    if let Some(m) = crate::re!(r"(?is)^(?:open|launch|ffne|oeffne)?\s*(?:(?:write|draft|compose|schreibe|schreib|verfasse)\s+(?:an\s+|a\s+|eine\s+)?(?:email|e-mail|mail|nachricht)\s+(?:to|an)\s+([\w\s@.-]+?)|(?:email|e-mail|mail)\s+([\w\s@.-]+?))(?:\s+(?:saying|with text|mit dem text|mit text|dass|das)\s+(.+))?$").captures(&text) {
        let name = m.get(1).or(m.get(2)).map(|x| x.as_str().trim().to_string()).unwrap_or_default();
        let body = m.get(3).map(|x| x.as_str().to_string()).unwrap_or_default();
        let email_re = crate::re!(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}");
        let lower = name.to_lowercase();
        let email = crate::personal::facts()
            .iter()
            .filter_map(|f| f["content"].as_str())
            .filter(|c| c.to_lowercase().contains(&lower) && c.contains('@'))
            .find_map(|c| email_re.find(c).map(|e| e.as_str().to_string()))
            .or_else(|| email_re.find(&name).map(|e| e.as_str().to_string()));
        let Some(email) = email else {
            return Some(ask(&format!("I don't have {name}'s email address in my memory. What is it?")));
        };
        if body.is_empty() {
            return Some(ask(&format!("What should I write to {name}?")));
        }
        return Some(vec![json!({ "action": "draft_email", "target": "Gmail", "recipient": email,
                                 "subject": format!("Message for {name}"), "content": body })]);
    }
    None
}

// ---- speech corrections -----------------------------------------------------------

/// Corrects the addressed assistant/app only; dictated message contents stay intact.
pub fn apply_speech_corrections(text: &str) -> String {
    let mut result = crate::re!(r"(?i)^((?:hey\s+)?)(?:travis|jarves)([,\s])").replace(text, "${1}JARVIS${2}").to_string();
    result = crate::re!(r"(?i)^((?:(?:hey\s+)?jarvis[, ]+)?(?:please\s+|bitte\s+)?(?:open|launch|start|öffne|oeffne|starte)\s+)(?:cloud code|clock code|quad code|clawed code|clod code)($|[.!?, ]+)")
        .replace(&result, "${1}Codex${2}")
        .to_string();
    if crate::re!(r"(?i)(?:email|e-mail|recipient|empfänger|adresse|to\s|an\s|ad\s)").is_match(&result) {
        result = crate::re!(r"(?i)\s+(?:dot|punkt|point)\s+").replace_all(&result, ".").to_string();
        result = crate::re!(r"(?i)\s+(?:at|ad|ät|äffchen)\s+").replace_all(&result, "@").to_string();
        result = crate::re!(r"(?i)\s+(?:strich|dash|minus)\s+").replace_all(&result, "-").to_string();
        result = crate::re!(r"(?i)\s+(?:unterstrich|underscore)\s+").replace_all(&result, "_").to_string();
    }
    if crate::re!(r"(?i)(?:email|e-?mail|gmail|outlook|antworte|empfänger)").is_match(&result) {
        let split = crate::re!(r"(?i)\b(?:saying|with\s+(?:the\s+)?(?:text|body)|message\s+is|body:|content:|message:|text:|mit\s+(?:dem\s+)?(?:text|inhalt)|und\s+text|inhalt:|dass)\b")
            .find(&result)
            .map(|m| m.start())
            .unwrap_or(result.len());
        let (head, tail) = result.split_at(split);
        let head = crate::re!(r"(?i)\bHerrn?\s+(?:Häner|Haener|Haner|Hener|Hänner|Haenner|Hanner)\b").replace_all(head, |c: &regex::Captures| {
            if c[0].to_lowercase().starts_with("herrn ") { "Herrn Häner" } else { "Herr Häner" }.to_string()
        });
        result = format!("{head}{tail}");
    }
    result
}

// ---- fast action detection --------------------------------------------------------

/// Keyword detection for short, obvious commands; everything else goes to the LLM.
pub fn detect_action_fast(text: &str) -> Option<&'static str> {
    let t = text.to_lowercase();
    let t = t.trim();
    if t.split_whitespace().count() > 12 {
        return None;
    }
    let any = |list: &[&str]| list.iter().any(|p| t.contains(p));
    if any(&["look at my screen", "what's on my screen", "whats on my screen", "what am i looking at", "what do you see", "see my screen", "what's running on my", "whats running on my", "check my screen"]) {
        return Some("describe_screen");
    }
    if any(&["open claude", "start claude", "launch claude", "run claude"]) {
        return Some("open_terminal");
    }
    if any(&["show me what you built", "pull up what you made", "open what you built"]) {
        return Some("show_recent");
    }
    if any(&["can you see my screen", "what's open", "whats open", "what apps are open"]) {
        return Some("describe_screen");
    }
    if any(&["what's my schedule", "whats my schedule", "what's on my calendar", "whats on my calendar", "do i have any meetings", "any meetings", "what's next on my calendar", "my schedule today", "what do i have today", "my calendar", "upcoming meetings", "next meeting", "what's my next meeting"]) {
        return Some("check_calendar");
    }
    if any(&["check my email", "check my mail", "any new emails", "any new mail", "unread emails", "unread mail", "what's in my inbox", "whats in my inbox", "read my email", "read my mail", "any emails", "any mail", "email update", "mail update"]) {
        return Some("check_mail");
    }
    if any(&["where are we", "where were we", "project status", "how's the build", "hows the build", "status update", "status report", "where is that", "how's it going with", "hows it going with", "is it done", "is that done", "what happened with"]) {
        return Some("check_dispatch");
    }
    if any(&["what's on my list", "whats on my list", "my tasks", "my to do", "my todo", "what do i need to do", "open tasks", "task list"]) {
        return Some("check_tasks");
    }
    if any(&["what are my notes", "whats in my notes", "what's in my notes", "check my notes", "read my notes", "show my notes", "list my notes", "my notes", "do i have any notes"]) {
        return Some("check_notes");
    }
    if any(&["what's new", "whats new", "what is new", "any updates", "was gibt's neues", "was gibts neues", "check tickets", "show tickets", "my tickets", "any new tickets", "what tickets", "read tickets"]) {
        return Some("check_tickets");
    }
    if any(&["usage", "how much have you cost", "how much am i spending", "what's the cost", "whats the cost", "api cost", "token usage", "how expensive", "what's my bill"]) {
        return Some("check_usage");
    }
    None
}

/// Casual chat during work mode goes to the fast model, not the coding agent.
pub fn is_casual_question(text: &str) -> bool {
    let t = text.to_lowercase();
    let t = t.trim();
    if t.split_whitespace().count() <= 3 && ["ok", "okay", "sure", "yes", "no", "yeah", "nah", "cool"].iter().any(|w| t.contains(w)) {
        return true;
    }
    [
        "what time", "what's the time", "what day", "what's the weather", "weather", "how are you", "are you there", "hey jarvis",
        "good morning", "good evening", "good night", "thank you", "thanks", "never mind", "nevermind", "stop", "cancel",
        "quit work mode", "exit work mode", "go back to chat", "regular mode", "how's it going", "what's up", "are you still there",
        "you there", "jarvis", "are you doing it", "is it working", "what happened", "did you hear me", "hello", "hey",
        "how's that coming", "hows that coming", "any update", "status update",
    ]
    .iter()
    .any(|p| t.contains(p))
}

/// Selects bounded relevant context for one voice turn.
pub fn relevant_context(text: &str, query: &str, budget: usize) -> String {
    let words: std::collections::HashSet<String> =
        crate::re!(r"\w{3,}").find_iter(&query.to_lowercase()).map(|m| m.as_str().to_string()).collect();
    if crate::re!(r"(?i)\b(?:what do you remember about me|what do you know about me|show (?:me )?(?:all )?(?:my )?memories|list (?:all )?(?:my )?memories|was wei(?:ss|ß)t du alles über mich|zeige (?:mir )?(?:alle )?erinnerungen|was hast du dir über mich gemerkt)\b").is_match(query) {
        return crate::util::take(text, budget.clamp(3000, 3800));
    }
    let mut budget = budget;
    if crate::re!(r"(?i)\b(?:yesterday|gestern|earlier|vorhin|zuletzt|recent conversation|last conversation|meeting|besprechung|termin|heute|today|routine|alltag)\b").is_match(query) {
        budget = budget.max(1700);
    }
    let lines: Vec<&str> = text.lines().filter(|l| !l.trim().is_empty()).collect();
    let mut ranked: Vec<(usize, usize, &str)> = lines
        .iter()
        .enumerate()
        .map(|(i, line)| {
            let score = crate::re!(r"\w{3,}").find_iter(&line.to_lowercase()).map(|m| m.as_str().to_string()).collect::<std::collections::HashSet<_>>().intersection(&words).count();
            (score, i, *line)
        })
        .filter(|r| r.0 > 0)
        .collect();
    ranked.sort_by(|a, b| b.0.cmp(&a.0).then(a.1.cmp(&b.1)));
    ranked.truncate(5);
    ranked.sort_by_key(|r| r.1);
    crate::util::take(&ranked.iter().map(|r| r.2).collect::<Vec<_>>().join("\n"), budget)
}

/// Up to two recent exchanges, bounded, followed by the current request.
pub fn recent_turns(history: &[Value], text: &str, budget: usize) -> Vec<Value> {
    let previous = match history.last() {
        Some(last) if last["role"] == "user" && last["content"] == text => &history[..history.len() - 1],
        _ => history,
    };
    let mut remaining = budget.saturating_sub(text.chars().count());
    let mut selected = Vec::new();
    for row in previous.iter().rev().take(4) {
        let Some(content) = row["content"].as_str() else { break };
        let content = crate::util::tail(content, 800);
        let len = content.chars().count();
        if len > remaining {
            break;
        }
        selected.push(json!({ "role": row["role"], "content": content }));
        remaining -= len;
    }
    selected.reverse();
    selected.push(json!({ "role": "user", "content": text }));
    selected
}
