//! Behavior tests ported from the former Python suite (tests/test_*.py).
//! They cover the pure logic behind Jarvis's safety rules; code that needs the
//! Windows host is exercised by scripts/verify-source.cjs instead.

use crate::apps::{App, parse_open_request, resolve_app};
use crate::desktop_agent::{Options, check_action};
use crate::intents::{direct_message_plan, fast_plan, message_send_requested};
use crate::local_pc::is_pc_request;
use crate::speech::is_banned_confirmation;
use crate::stt::clean_transcript;
use crate::websites::parse_website_request;
use serde_json::{Value, json};

fn node(id: i64, name: &str, role: &str, value: &str) -> Value {
    json!({ "id": id, "name": name, "role": role, "value": value })
}

/// The fields that define a message draft (an empty subject is ignored).
fn message_steps(plan: Option<Vec<Value>>) -> Option<Value> {
    plan.map(|steps| steps.iter().map(|s| json!({ "action": s["action"], "target": s["target"], "recipient": s["recipient"], "content": s["content"] })).collect())
}

fn with(mut base: Value, extra: Value) -> Value {
    if let (Some(b), Some(e)) = (base.as_object_mut(), extra.as_object()) {
        b.extend(e.clone());
    }
    base
}

// ---- transcript guard (test_transcript_guard.py) -----------------------------------

#[test]
fn transcript_guard_keeps_normal_text() {
    assert_eq!(clean_transcript("Open Outlook"), "Open Outlook");
    assert_eq!(clean_transcript("What is the weather today?"), "What is the weather today?");
    assert_eq!(clean_transcript("  hello jarvis  "), "hello jarvis");
}

#[test]
fn transcript_guard_drops_hallucinations() {
    for text in ["신나고.", "這就比較少了", "Сега така?", "А оу", "مرحبا بك", "Thanks for watching!", "Subtitles by Amara", "Translated by"] {
        assert_eq!(clean_transcript(text), "", "{text}");
    }
    assert_eq!(clean_transcript("Windows App Namen outlook whatsapp snapchat mullvad forticlient"), "");
}

// ---- spoken confirmations (test_banned_confirmations_and_silent_drafts.py) -------------

#[test]
fn filler_confirmations_are_never_spoken() {
    for phrase in [
        "I am working on your task", "I'm working on your task, sir.", "Working on your task", "On it", "On it, sir.", "On it!",
        "I'm on it, sir.", "Building it now, sir.", "Building that now, sir.", "Understood, sir.", "Understood.", "Right away.",
        "Looking into that now, sir.", "Looking into it now, sir.", "Connecting to project now, sir.", "Connecting now, sir.",
        "Claude Code is working in project.", "Codex is working in project.", "Consider it done.", "Will do, sir.", "Certainly.",
        "Still working on it, sir.", "Working on it, sir.", "Getting right on that, sir.", "I will get right on that, sir.",
        "Starting now, sir.", "Opened Gmail composer for alex@example.com.", "Opened Outlook composer.", "Ich bin dran, Sir.",
        "Wird erledigt, Sir.", "Verstanden.", "Ich arbeite an Ihrer Aufgabe.", "On it, sir. Building it now, sir.",
        "Understood, sir. Right away, sir.",
    ] {
        assert!(is_banned_confirmation(phrase), "{phrase}");
    }
}

#[test]
fn real_answers_are_spoken() {
    for phrase in [
        "Testing audio, sir.", "Something went wrong, sir.", "Opening Google Chrome.", "Saved notes.txt to your Desktop.",
        "Here is the summary of your emails.", "The weather in Paris is sunny and 22 degrees.", "Which app do you mean: Chrome or Firefox?",
        "Who is the message for, and what should it say?", "Understood, sir. Here is the answer you requested: 42.",
        "I found 3 emails from Alex in your inbox.", "Available drives: drive C, drive D.", "The app could not be started. Please try again.",
    ] {
        assert!(!is_banned_confirmation(phrase), "{phrase}");
    }
}

// ---- websites (test_websites.py) ---------------------------------------------------------

#[test]
fn spoken_domains_and_named_sites() {
    for phrase in ["Öffne youtube.com", "Open youtube.com", "Jarvis, öffne bitte youtube punkt com"] {
        assert_eq!(parse_website_request(phrase).as_deref(), Some("youtube.com"), "{phrase}");
    }
    assert_eq!(parse_website_request("Öffne Outlook"), None);
    assert_eq!(parse_website_request(r"Öffne Ordner C:\Users"), None);
    for phrase in ["Open dashboard", "Open the dashboard.", "Öffne das Dashboard", "Open Jarvis dashboard in Chrome"] {
        assert_eq!(parse_website_request(phrase).as_deref(), Some("jarvis:dashboard"), "{phrase}");
    }
    for phrase in ["Open YouTube", "Open YouTube.", "Open YouTube in Chrome"] {
        assert_eq!(parse_website_request(phrase).as_deref(), Some("https://www.youtube.com"), "{phrase}");
    }
    for phrase in ["Open Gmail", "Open Gmail.", "Open Gmail in Chrome"] {
        assert_eq!(parse_website_request(phrase).as_deref(), Some("https://mail.google.com/"), "{phrase}");
    }
}

// ---- app identity (test_app_launcher.py) -------------------------------------------------

fn catalog() -> Vec<App> {
    [
        ("Google Chrome", "Chrome"), ("Outlook", "Outlook.New!App"), ("Outlook (classic)", "Outlook.Classic"),
        ("WhatsApp", "WhatsApp!App"), ("Snapchat", "Snapchat!App"), ("Proton VPN", "Proton"), ("Mullvad VPN", "Mullvad"),
        ("FortiClient VPN", "Forti"), ("Rechner", "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"),
        ("Editor", "Microsoft.WindowsNotepad_8wekyb3d8bbwe!App"), ("Registrierungs-Editor", r"C:\Windows\regedit.exe"),
        ("Calculator Tools 10.0", r"C:\Users\Samir\KiCad\pcb_calculator.exe"),
    ]
    .into_iter()
    .map(|(name, id)| App { name: name.into(), id: id.into(), executable: None })
    .collect()
}

#[test]
fn spoken_open_commands() {
    let one = |p: &str| parse_open_request(p);
    for (phrase, app) in [
        ("Öffne Chrome", "Chrome"), ("Jarvis, öffne bitte Chrome!", "Chrome"), ("Kannst du bitte Chrome öffnen?", "Chrome"),
        ("Mach Chrome auf", "Chrome"), ("Please open Chrome", "Chrome"), ("Outlook öffnen", "Outlook"), ("Open Outlook", "Outlook"),
        ("Open my Outlook", "Outlook"), ("Open Outlook mail", "Outlook"), ("Open the Outlook app", "Outlook"),
        ("Open Microsoft Outlook", "Outlook"), ("Öffne mein Outlook", "Outlook"), ("Mach Outlook auf", "Outlook"),
        ("Öffne das Outlook-Programm", "Outlook"), ("Öffne mir Excel", "Excel"), ("Mach mir mal Chrome auf", "Chrome"),
    ] {
        assert_eq!(one(phrase), Some(vec![app.to_string()]), "{phrase}");
    }
    assert_eq!(one("Öffne mir Chrome und Outlook"), Some(vec!["Chrome".to_string(), "Outlook".to_string()]));
    for phrase in ["Öffne https://example.com", "Verbinde mein VPN", "Öffne den Projektordner"] {
        assert_eq!(one(phrase), None, "{phrase}");
    }
}

#[test]
fn aliases_and_exact_outlook_preference() {
    let apps = catalog();
    let first = |q: &str| resolve_app(q, &apps).first().map(|a| (a.name.clone(), a.id.clone()));
    assert_eq!(first("Chrome").unwrap().1, "Chrome");
    assert_eq!(first("Outlook").unwrap().1, "Outlook.New!App");
    assert_eq!(first("Whats App").unwrap().0, "WhatsApp");
    assert_eq!(first("Snap Chat").unwrap().0, "Snapchat");
    assert_eq!(first("Calculator").unwrap().0, "Rechner");
    assert_eq!(first("Notepad").unwrap().0, "Editor");
    assert_eq!(first("Calculator Tools 10.0").unwrap().0, "Calculator Tools 10.0");
    assert_eq!(resolve_app("VPN", &apps).len(), 3);
}

#[test]
fn spoken_article_is_dropped_only_when_needed() {
    let mut apps = catalog();
    let first = |q: &str, apps: &[App]| resolve_app(q, apps).first().map(|a| a.name.clone());
    assert_eq!(first("den Rechner", &apps).as_deref(), Some("Rechner"));
    assert_eq!(first("the calculator", &apps).as_deref(), Some("Rechner"));
    assert_eq!(first("den Editor", &apps).as_deref(), Some("Editor"));
    assert_eq!(resolve_app("mein Chrome", &apps)[0].id, "Chrome");
    assert!(resolve_app("den Taschenrechner Pro", &apps).is_empty());
    apps.push(App { name: "Die Siedler".into(), id: "Siedler".into(), executable: None });
    apps.push(App { name: "Siedler Tools".into(), id: "Tools".into(), executable: None });
    let ids: Vec<String> = resolve_app("Die Siedler", &apps).into_iter().map(|a| a.id).collect();
    assert_eq!(ids, ["Siedler"]);
}

// ---- PC control parsing (test_pc_control.py) ---------------------------------------------

#[test]
fn questions_are_not_pc_actions() {
    for text in ["Was sind Viren?", "Kann Codex Apps programmieren?", r"Lösche C:\Windows", "Öffne Chrome"] {
        assert!(crate::pc_control::parse(text).is_none(), "{text}");
    }
    for (text, action) in [("Scanne meinen ganzen PC", "scan"), ("Starte Schnellscan", "scan"), ("Programmiere mir eine App", "code"), (r"Öffne Ordner C:\Users", "open_path")] {
        assert_eq!(crate::pc_control::parse(text).map(|c| c.0), Some(action), "{text}");
    }
}

// ---- voice routing (test_email_workflows.py, test_local_pc.py) ------------------------------

#[test]
fn mail_work_routes_to_the_pc_agent_but_plain_opens_do_not() {
    for text in [
        "Open Outlook and write an email", "Open Gmail in Chrome and compose an email", "Read old emails in Outlook",
        "Find Gmail emails from last month", "Schreibe eine Mail in Outlook", "Lies alte E-Mails in Gmail", "Check my email",
        "Any new emails?", "Prüfe meinen Posteingang", "Write an email in Outlook",
    ] {
        assert!(is_pc_request(text), "{text}");
    }
    for text in ["What is Gmail?", "Open Gmail", "Open Outlook", "Open my Outlook", "Open Outlook mail", "Open the Outlook app", "Öffne mein Outlook"] {
        assert!(!is_pc_request(text), "{text}");
    }
}

#[test]
fn explicit_local_reads_have_exact_fast_plans() {
    let file = fast_plan(r#"Read the file "C:\Users\Samir\Documents\notes for Jarvis.txt"."#).unwrap();
    assert_eq!((file[0]["action"].as_str(), file[0]["target"].as_str()), (Some("read_file"), Some(r"C:\Users\Samir\Documents\notes for Jarvis.txt")));
    for request in [r#"Read files "C:\Users\Samir\a.txt" and "C:\Users\Samir\b.md""#, r#"Lies die Dateien "C:\Users\Samir\a.txt" und "C:\Users\Samir\b.md""#] {
        let batch = fast_plan(request).unwrap();
        let targets: Vec<&str> = batch.iter().filter_map(|s| s["target"].as_str()).collect();
        assert_eq!(targets, [r"C:\Users\Samir\a.txt", r"C:\Users\Samir\b.md"], "{request}");
        assert!(batch.iter().all(|s| s["action"] == "read_file"));
    }
    assert!(is_pc_request(r#"Lies die Dateien "C:\Users\Samir\a.txt" und "C:\Users\Samir\b.md""#));
    assert!(fast_plan(r#"Read files "C:\Users\Samir\a.txt" and "C:\Users\Samir\b.md" and summarize them"#).is_none());
    let folder = fast_plan(r"List the folder C:\Users\Samir\Documents").unwrap();
    assert_eq!((folder[0]["action"].as_str(), folder[0]["target"].as_str()), (Some("list_folder"), Some(r"C:\Users\Samir\Documents")));
    assert!(fast_plan(r"Read the file C:\Users\Samir\note.txt and open Chrome").is_none());
}

#[test]
fn chatgpt_and_claude_prompts_are_fast_and_distinct() {
    for (phrase, action, content) in [
        ("Open ChatGPT and prompt it to improve Jarvis v5", "chatgpt_prompt", "improve Jarvis v5"),
        ("Open Claude and tell it to change the Jarvis meeting memory", "claude_prompt", "change the Jarvis meeting memory"),
        ("Tell Claude to improve the German name recognition", "claude_prompt", "improve the German name recognition"),
        ("Öffne Claude und sage ihm verbessere Jarvis v5", "claude_prompt", "verbessere Jarvis v5"),
        ("Frag Claude, wie hoch der Eiffelturm ist", "claude_prompt", "wie hoch der Eiffelturm ist"),
        ("Sag Claude er soll Jarvis verbessern", "claude_prompt", "Jarvis verbessern"),
        ("Schreib Claude dass die Tests fehlschlagen", "claude_prompt", "die Tests fehlschlagen"),
        ("Frage ChatGPT was ein Transformer ist", "chatgpt_prompt", "was ein Transformer ist"),
    ] {
        assert!(is_pc_request(phrase), "{phrase}");
        let plan = fast_plan(phrase).unwrap_or_else(|| panic!("no fast plan: {phrase}"));
        assert_eq!((plan[0]["action"].as_str(), plan[0]["content"].as_str()), (Some(action), Some(content)), "{phrase}");
    }
}

// ---- messages (test_teams_message.py) ------------------------------------------------------

#[test]
fn exact_messages_are_planned_locally_and_send_is_intent_only() {
    let teams = json!([{ "action": "draft_message", "target": "Teams", "recipient": "Samir Sali", "content": "Jarvis test" }]);
    for command in [
        "Send a Teams message to Samir Sali saying Jarvis test",
        "Open Teams and send a message to Samir Sali saying Jarvis test",
        "Schicke eine Teams Nachricht an Samir Sali mit dem Text Jarvis test",
    ] {
        assert_eq!(message_steps(fast_plan(command)), Some(teams.clone()), "{command}");
    }
    assert!(direct_message_plan("Send a Teams message to Samir Sali").is_none());
    let snap = json!([{ "action": "draft_message", "target": "Snapchat", "recipient": "Branko", "content": "Send me the notes." }]);
    assert_eq!(message_steps(fast_plan("Open Snapchat and write a message to Branko saying Send me the notes.")), Some(snap));
    let whatsapp = json!([{ "action": "draft_message", "target": "WhatsApp", "recipient": "Branko", "content": "See you soon!" }]);
    assert_eq!(message_steps(fast_plan("Write a WhatsApp message to Branko saying See you soon!")), Some(whatsapp));
    assert!(!message_send_requested("Open Snapchat and write a message to Branko saying Send me the notes."));
    assert!(message_send_requested("Open Snapchat and send a message to Branko saying Hello!"));
}

// ---- desktop action guard (test_desktop_agent.py, test_teams_message.py) ---------------------

#[test]
fn existing_text_and_passwords_are_protected() {
    let action = json!({ "action": "type", "element": 0, "text": "replacement" });
    for n in [node(0, "Message", "Edit", "existing"), node(0, "Password", "Edit", ""), with(node(0, "Unknown", "Edit", ""), json!({ "value_known": false }))] {
        assert!(check_action(&action, &[n.clone()], &Options::default()).is_err(), "{n}");
    }
}

#[test]
fn send_requires_explicit_intent() {
    let send = [node(1, "Send", "Button", "")];
    let click = json!({ "action": "click", "element": 1 });
    assert!(check_action(&click, &send, &Options::default()).is_err());
    let allowed = Options { submit_allowed: true, ..Default::default() };
    assert!(check_action(&click, &send, &allowed).is_ok());
    assert!(check_action(&click, &[node(1, "Delete", "Button", "")], &allowed).is_err());
}

#[test]
fn literal_message_needs_one_matching_conversation_heading() {
    let action = json!({ "action": "type", "element": 0, "text": "Hello" });
    let franco = Options { literal: "Hello".into(), recipient: "Franco".into(), ..Default::default() };
    let heading = |id| with(node(id, "Franco", "Header", ""), json!({ "in_list": false }));
    let elements = vec![node(0, "Message", "Edit", ""), heading(1)];
    assert!(check_action(&action, &elements, &franco).is_ok());
    assert!(check_action(&action, &elements[..1], &franco).is_err());
    let mut doubled = elements.clone();
    doubled.push(heading(2));
    assert!(check_action(&action, &doubled, &franco).is_err());
    let other_text = json!({ "action": "type", "element": 0, "text": "Different text" });
    assert!(check_action(&other_text, &elements, &franco).is_err());
}

#[test]
fn repeated_message_authors_do_not_override_the_chat_heading() {
    let nodes = vec![
        node(0, "Message", "Edit", ""),
        with(node(1, "Samir Sali", "Text", ""), json!({ "in_list": true, "conversation_heading": true })),
        with(node(2, "Samir Sali", "Text", ""), json!({ "in_list": false })),
        with(node(3, "Other Person", "Text", ""), json!({ "in_list": false })),
    ];
    let action = json!({ "action": "type", "element": 0, "text": "Jarvis test" });
    let samir = Options { literal: "Jarvis test".into(), recipient: "Samir Sali".into(), ..Default::default() };
    assert!(check_action(&action, &nodes, &samir).is_ok());
    let other = Options { literal: "Jarvis test".into(), recipient: "Other Person".into(), ..Default::default() };
    let error = check_action(&action, &nodes, &other).unwrap_err();
    assert!(error.contains("conversation heading"), "{error}");
}
