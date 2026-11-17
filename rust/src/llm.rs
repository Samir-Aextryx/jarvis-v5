//! Unified OpenAI (Responses API), Gemini, Grok and Ollama Cloud client.

use crate::config;
use crate::host::{Http, HttpResponse, Res};
use crate::settings::{self, Provider, provider_config, provider_model, validate_model};
use crate::vault;
use serde_json::{Value, json};

pub struct Llm {
    pub provider: &'static Provider,
    key: String,
}

pub struct Request<'a> {
    pub messages: Vec<Value>,
    pub system: &'a str,
    pub max_tokens: u32,
    pub model: Option<&'a str>,
    pub json_schema: Option<Value>,
}

impl<'a> Request<'a> {
    pub fn new(system: &'a str, messages: Vec<Value>, max_tokens: u32) -> Self {
        Self { messages, system, max_tokens, model: None, json_schema: None }
    }
    pub fn user(system: &'a str, text: &str, max_tokens: u32) -> Self {
        Self::new(system, vec![json!({ "role": "user", "content": text })], max_tokens)
    }
}

pub fn user_msg(text: &str) -> Value {
    json!({ "role": "user", "content": text })
}

impl Llm {
    pub fn new(provider: Option<&str>, key: Option<String>) -> Res<Self> {
        let provider = provider_config(provider)?;
        let key = key.unwrap_or_else(|| vault::get(provider.key_name));
        Ok(Self { provider, key })
    }
    /// The selected provider, if its key is configured.
    pub fn active() -> Option<Self> {
        Self::new(None, None).ok().filter(|c| !c.key.is_empty())
    }
    pub fn has_key(&self) -> bool {
        !self.key.is_empty()
    }
    fn require_key(&self) -> Res<()> {
        if self.key.is_empty() {
            return Err(format!("{} API key is missing. Add it in Settings.", self.provider.label));
        }
        Ok(())
    }

    fn inputs(messages: &[Value], chat: bool) -> Res<Vec<Value>> {
        let mut out = Vec::new();
        for m in messages {
            let content = match &m["content"] {
                Value::Array(blocks) => {
                    let mut parts = Vec::new();
                    for block in blocks {
                        match block["type"].as_str() {
                            Some("text") => parts.push(json!({ "type": if chat { "text" } else { "input_text" }, "text": block["text"] })),
                            Some("image") => {
                                let src = &block["source"];
                                let url = format!("data:{};base64,{}", src["media_type"].as_str().unwrap_or(""), src["data"].as_str().unwrap_or(""));
                                parts.push(if chat {
                                    json!({ "type": "image_url", "image_url": { "url": url } })
                                } else {
                                    json!({ "type": "input_image", "image_url": url })
                                });
                            }
                            _ => return Err("Unsupported message content".into()),
                        }
                    }
                    Value::Array(parts)
                }
                other => other.clone(),
            };
            out.push(json!({ "role": m["role"], "content": content }));
        }
        Ok(out)
    }

    fn chat_payload(&self, req: &Request) -> Res<Value> {
        let mut inputs = Self::inputs(&req.messages, true)?;
        if !req.system.is_empty() {
            inputs.insert(0, json!({ "role": "system", "content": req.system }));
        }
        let model = match req.model {
            Some(m) => validate_model(m)?,
            None => provider_model(self.provider)?,
        };
        let mut payload = json!({ "model": model, "messages": inputs, "max_tokens": req.max_tokens.max(16) });
        let effort = config::get_or("OPENAI_REASONING_EFFORT", "low");
        if self.provider.id == "gemini" {
            payload["reasoning_effort"] = json!(if ["minimal", "low", "medium", "high"].contains(&effort.as_str()) { effort.as_str() } else { "low" });
        } else if self.provider.id == "ollama" {
            let mapped = if model.split(':').next() == Some("gpt-oss") {
                // GPT-OSS always reasons; "low" is its fastest level and it cannot answer directly.
                match effort.as_str() {
                    "medium" => "medium",
                    "high" | "xhigh" | "max" => "high",
                    _ => "low",
                }
            } else {
                // DeepSeek on Ollama thinks at "high" unless told otherwise; "none" answers directly.
                match effort.as_str() {
                    "medium" => "high",
                    "xhigh" => "max",
                    e if ["none", "low", "high", "max"].contains(&e) => e,
                    _ => "low",
                }
            };
            payload["reasoning_effort"] = json!(mapped);
            if mapped != "none" {
                // Ollama counts the reasoning trace against max_tokens; keep the answer's budget.
                payload["max_tokens"] = json!(req.max_tokens.max(16) + 1024);
            }
        }
        if let Some(schema) = &req.json_schema {
            payload["response_format"] = json!({ "type": "json_schema", "json_schema": { "name": "pc_plan", "strict": true, "schema": schema } });
        }
        Ok(payload)
    }

    fn openai_model(req: &Request) -> String {
        req.model.map(str::to_string).unwrap_or_else(|| config::get_or("OPENAI_MODEL", "gpt-6-luna"))
    }

    /// One complete text response.
    pub async fn create(&self, req: &Request<'_>) -> Res<String> {
        self.require_key()?;
        let label = self.provider.label;
        if self.provider.id != "openai" {
            let payload = self.chat_payload(req)?;
            let mut response = Http::post(self.provider.endpoint).bearer(&self.key).timeout(90.0).json(&payload).send().await?;
            if response.status != 200 {
                return Err(format!("{label} API HTTP {}; check key, model and API credit.", response.status));
            }
            let data = response.json().await?;
            let choice = &data["choices"][0];
            let text = choice["message"]["content"].as_str().unwrap_or("");
            if choice["finish_reason"] != "stop" || text.trim().is_empty() {
                return Err(format!("{label} returned no complete text response."));
            }
            settings::track_usage(data["usage"]["prompt_tokens"].as_u64().unwrap_or(0), data["usage"]["completion_tokens"].as_u64().unwrap_or(0));
            return Ok(text.to_string());
        }
        let model = Self::openai_model(req);
        let mut payload = json!({ "model": model, "input": Self::inputs(&req.messages, false)?,
                                  "max_output_tokens": req.max_tokens.max(16), "store": false });
        if model == "gpt-6-luna" {
            payload["reasoning"] = json!({ "effort": config::get_or("OPENAI_REASONING_EFFORT", "low") });
        }
        if !req.system.is_empty() {
            payload["instructions"] = json!(req.system);
        }
        if let Some(schema) = &req.json_schema {
            payload["text"] = json!({ "format": { "type": "json_schema", "name": "pc_plan", "strict": true, "schema": schema } });
        }
        let mut response = Http::post(self.provider.endpoint).bearer(&self.key).timeout(90.0).json(&payload).send().await?;
        if response.status != 200 {
            // Never propagate API keys or request bodies into logs or the UI.
            return Err(format!("OpenAI API HTTP {}; check key, model and API credit.", response.status));
        }
        let data = response.json().await?;
        let mut text = String::new();
        for item in data["output"].as_array().into_iter().flatten() {
            if item["type"] != "message" {
                continue;
            }
            for part in item["content"].as_array().into_iter().flatten() {
                if part["type"] == "output_text" {
                    text.push_str(part["text"].as_str().unwrap_or(""));
                }
            }
        }
        if text.is_empty() {
            return Err("OpenAI returned no text; check the model and output token limit.".into());
        }
        settings::track_usage(data["usage"]["input_tokens"].as_u64().unwrap_or(0), data["usage"]["output_tokens"].as_u64().unwrap_or(0));
        Ok(text)
    }

    /// Streams text deltas; dropping the stream closes the HTTP request.
    pub async fn stream(&self, req: &Request<'_>) -> Res<Stream> {
        self.require_key()?;
        let chat = self.provider.id != "openai";
        let payload = if chat {
            let mut p = self.chat_payload(req)?;
            p["stream"] = json!(true);
            p["stream_options"] = json!({ "include_usage": true });
            p
        } else {
            let model = Self::openai_model(req);
            let mut p = json!({ "model": model, "input": req.messages, "instructions": req.system,
                                "max_output_tokens": req.max_tokens, "store": false, "stream": true });
            if model == "gpt-6-luna" {
                p["reasoning"] = json!({ "effort": config::get_or("OPENAI_REASONING_EFFORT", "low") });
            }
            p
        };
        let response = Http::post(self.provider.endpoint).bearer(&self.key).timeout(90.0).json(&payload).send().await?;
        if response.status != 200 {
            return Err(if chat {
                format!("{} API HTTP {}; check key, model and API credit.", self.provider.label, response.status)
            } else {
                format!("OpenAI API HTTP {}", response.status)
            });
        }
        Ok(Stream { response, chat, label: self.provider.label, buffer: Vec::new(), queue: Vec::new(), finished: false, done: false, ended: false })
    }
}

pub struct Stream {
    response: HttpResponse,
    chat: bool,
    label: &'static str,
    buffer: Vec<u8>,
    queue: Vec<String>,
    finished: bool,
    done: bool,
    ended: bool,
}

impl Stream {
    /// Next text delta, or None when the response completed normally.
    pub async fn next(&mut self) -> Res<Option<String>> {
        loop {
            if !self.queue.is_empty() {
                return Ok(Some(self.queue.remove(0)));
            }
            if self.ended {
                return Ok(None);
            }
            if let Some(pos) = self.buffer.iter().position(|b| *b == b'\n') {
                let line: Vec<u8> = self.buffer.drain(..=pos).collect();
                let line = String::from_utf8_lossy(&line).trim().to_string();
                self.event(&line)?;
                continue;
            }
            match self.response.chunk().await? {
                Some(chunk) => self.buffer.extend_from_slice(&chunk),
                None => {
                    if !self.buffer.is_empty() {
                        let line = String::from_utf8_lossy(&std::mem::take(&mut self.buffer)).trim().to_string();
                        self.event(&line)?;
                        continue;
                    }
                    self.ended = true;
                    let complete = if self.chat { self.finished && self.done } else { self.finished };
                    if !complete {
                        return Err(format!("{} stream ended before completion.", self.label));
                    }
                }
            }
        }
    }

    fn event(&mut self, line: &str) -> Res<()> {
        let Some(raw) = line.strip_prefix("data:") else { return Ok(()) };
        let raw = raw.trim();
        if raw == "[DONE]" {
            if self.chat {
                self.done = true;
                self.ended = true;
            }
            return Ok(());
        }
        let event: Value = serde_json::from_str(raw).map_err(|e| e.to_string())?;
        if self.chat {
            if !event["error"].is_null() {
                return Err(format!("{} stream failed.", self.label));
            }
            if event["usage"].is_object() {
                settings::track_usage(event["usage"]["prompt_tokens"].as_u64().unwrap_or(0), event["usage"]["completion_tokens"].as_u64().unwrap_or(0));
            }
            for choice in event["choices"].as_array().into_iter().flatten() {
                if let Some(reason) = choice["finish_reason"].as_str() {
                    if reason != "stop" {
                        return Err(format!("{} stream did not complete normally.", self.label));
                    }
                    self.finished = true;
                }
                if let Some(delta) = choice["delta"]["content"].as_str().filter(|d| !d.is_empty()) {
                    self.queue.push(delta.to_string());
                }
            }
        } else {
            match event["type"].as_str().unwrap_or("") {
                "response.output_text.delta" => self.queue.push(event["delta"].as_str().unwrap_or("").to_string()),
                "response.completed" => {
                    self.finished = true;
                    let usage = &event["response"]["usage"];
                    settings::track_usage(usage["input_tokens"].as_u64().unwrap_or(0), usage["output_tokens"].as_u64().unwrap_or(0));
                }
                "error" | "response.failed" | "response.incomplete" => return Err("OpenAI stream did not complete.".into()),
                _ => {}
            }
        }
        Ok(())
    }
}
