/** Local personal workspace: no HTML interpolation of saved user content. */
type View = 'memory' | 'calendar';
interface Fact { key: string; kind: string; content: string; updated: number; manual: number }
interface EventRow { id: string; version: number; title: string; start: string; end: string; all_day: boolean; description: string; location: string }
let dialog: HTMLDialogElement;
let view: View = 'memory';
let facts: Fact[] = [], events: EventRow[] = [];
let currentFact: Fact | undefined, currentEvent: EventRow | undefined;
let month = new Date(new Date().getFullYear(), new Date().getMonth(), 1);
let selectedDay = dateKey(new Date());
let loading = 0;
let previousFocus: HTMLElement | null;

function dateKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
}
function shiftDay(key: string, days: number): string {
  const d = new Date(key + 'T12:00:00'); d.setDate(d.getDate()+days); return dateKey(d);
}
function el<T extends HTMLElement = HTMLElement>(id: string): T { return dialog.querySelector('#'+id)! as T; }
function input(id: string): HTMLInputElement { return el<HTMLInputElement>(id); }
function message(text: string, error = false) { el('personal-status').textContent = text; el('personal-status').classList.toggle('error', error); }
async function api<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {method: body === undefined ? 'GET' : 'POST', headers: {
    'Authorization': 'Bearer '+(localStorage.getItem('jarvis_auth_token') || ''),
    ...(body === undefined ? {} : {'Content-Type':'application/json'})},
    ...(body === undefined ? {} : {body:JSON.stringify(body)})});
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Could not save. Check the fields and try again.');
  return data;
}
function button(text: string, click: () => void, cls = ''): HTMLButtonElement {
  const b=document.createElement('button'); b.type='button'; b.textContent=text; b.className=cls; b.onclick=click; return b;
}
async function act(form: string, work: () => Promise<void>) {
  const controls = Array.from(el(form).querySelectorAll<HTMLButtonElement>('button'));
  controls.forEach(b=>b.disabled=true);
  message('Saving…');
  try { await work(); message('Saved on this PC.'); }
  catch (error) { message(error instanceof Error ? error.message : 'Could not save.', true); }
  finally { controls.forEach(b=>b.disabled=false); }
}

function createDialog() {
  dialog=document.createElement('dialog'); dialog.id='personal-panel'; dialog.setAttribute('aria-labelledby','personal-heading');
  dialog.innerHTML=`
    <header class="personal-header"><div><p class="personal-eyebrow">JARVIS · PERSONAL SPACE</p><h2 id="personal-heading">Your memory</h2></div><button type="button" id="personal-close" aria-label="Close personal space">×</button></header>
    <nav class="personal-tabs" aria-label="Personal space"><button type="button" id="personal-memory-tab">Memory</button><button type="button" id="personal-calendar-tab">Calendar</button><button type="button" id="personal-refresh">Refresh</button><span>Stored on this PC</span></nav>
    <p id="personal-status" role="status" aria-live="polite"></p>
    <section id="personal-memory" class="personal-body">
      <div class="personal-list-column"><div class="personal-tools"><input id="memory-search" type="search" placeholder="Search memories" aria-label="Search memories"><button type="button" id="memory-new">+ New memory</button></div><div id="memory-list" class="personal-list"></div></div>
      <form id="memory-form" class="personal-editor"><h3 id="memory-editor-heading">New memory</h3><label for="memory-kind">Category</label><select id="memory-kind"><option value="fact">Fact</option><option value="preference">Preference</option><option value="routine">Routine</option><option value="goal">Goal</option><option value="project">Project</option></select><label for="memory-content">What should Jarvis remember?</label><textarea id="memory-content" rows="7" required maxlength="4000" placeholder="I prefer meetings in the morning."></textarea><p class="personal-hint">Your edits take priority over automatic learning. Jarvis uses relevant memories in conversation. Keep passwords and API keys in Settings.</p><div class="personal-actions"><button type="submit">Save memory</button><button type="button" id="memory-delete" class="personal-delete" hidden>Delete memory</button></div></form>
    </section>
    <section id="personal-calendar" class="personal-body" hidden>
      <div class="personal-list-column"><div class="personal-tools"><button type="button" id="month-prev" aria-label="Previous month">‹</button><h3 id="month-title"></h3><button type="button" id="month-next" aria-label="Next month">›</button><button type="button" id="calendar-today">Today</button></div><div class="calendar-weekdays" aria-hidden="true"><span>Mon</span><span>Tue</span><span>Wed</span><span>Thu</span><span>Fri</span><span>Sat</span><span>Sun</span></div><div id="calendar-grid"></div><div class="personal-tools"><h3 id="calendar-day-title"></h3><button type="button" id="event-new">+ New event</button></div><div id="event-list" class="personal-list"></div><p id="calendar-zone" class="personal-hint"></p></div>
      <form id="event-form" class="personal-editor"><h3 id="event-editor-heading">New event</h3><label for="event-title">Title</label><input id="event-title" required maxlength="200" placeholder="Dentist"><label class="personal-check"><input id="event-all-day" type="checkbox"> All day</label><label for="event-start">Start</label><input id="event-start" type="datetime-local" required><label for="event-end" id="event-end-label">End</label><input id="event-end" type="datetime-local" required><label for="event-location">Location</label><input id="event-location" maxlength="4000" placeholder="Optional"><label for="event-description">Notes</label><textarea id="event-description" rows="3" maxlength="4000" placeholder="Optional"></textarea><div class="personal-actions"><button type="submit">Save event</button><button type="button" id="event-delete" class="personal-delete" hidden>Delete event</button></div><p class="personal-hint">Your Jarvis calendar is separate from Google. Say “Create a calendar event…” to use it. No reminder notifications yet.</p></form>
    </section>`;
  document.body.append(dialog);
  el('personal-close').onclick=()=>dialog.close();
  dialog.addEventListener('close',()=>previousFocus?.focus());
  el('personal-memory-tab').onclick=()=>void openPersonalPanel('memory');
  el('personal-calendar-tab').onclick=()=>void openPersonalPanel('calendar');
  el('personal-refresh').onclick=()=>void openPersonalPanel(view);
  el('memory-new').onclick=()=>editMemory();
  input('memory-search').oninput=renderMemories;
  el('memory-form').onsubmit=(event)=>{event.preventDefault(); void act('memory-form',async()=>{
    const saved=await api<{fact:Fact}>('/api/memory/custom',{key:currentFact?.key,expected_updated:currentFact?.updated,kind:input('memory-kind').value,content:input('memory-content').value});
    await loadMemory(); editMemory(saved.fact);
  });};
  el('memory-delete').onclick=()=>{const fact=currentFact; if (!fact || !confirm('Delete this saved memory?')) return;
    void act('memory-form',async()=>{await api('/api/memory/delete',{key:fact.key,expected_updated:fact.updated}); await loadMemory(); editMemory();});};
  el('month-prev').onclick=()=>changeMonth(-1); el('month-next').onclick=()=>changeMonth(1);
  el('calendar-today').onclick=()=>{selectedDay=dateKey(new Date());month=new Date(new Date().getFullYear(),new Date().getMonth(),1);editEvent();void loadCalendar().catch(showLoadError);};
  el('event-new').onclick=()=>editEvent();
  input('event-all-day').onchange=()=>{
    const start=input('event-start').value, end=input('event-end').value;
    const allDay=input('event-all-day').checked;
    input('event-start').type=input('event-end').type=allDay?'date':'datetime-local';
    input('event-start').value=(start.slice(0,10)||selectedDay)+(allDay?'':'T09:00');
    input('event-end').value=(end.slice(0,10)||selectedDay)+(allDay?'':'T10:00');
    el('event-end-label').textContent=allDay?'Last day (included)':'End';
  };
  el('event-form').onsubmit=(event)=>{event.preventDefault();void act('event-form',async()=>{
    const allDay=input('event-all-day').checked;
    const saved=await api<{event:EventRow}>('/api/local-calendar/events',{id:currentEvent?.id,version:currentEvent?.version,title:input('event-title').value,start:input('event-start').value,end:allDay?shiftDay(input('event-end').value,1):input('event-end').value,all_day:allDay,location:input('event-location').value,description:input('event-description').value});
    selectedDay=saved.event.start.slice(0,10);month=new Date(selectedDay.slice(0,7)+'-01T12:00:00');
    await loadCalendar(); editEvent(saved.event);
  });};
  el('event-delete').onclick=()=>{const event=currentEvent;if (!event || !confirm('Delete this Jarvis calendar event?')) return;
    void act('event-form',async()=>{await api('/api/local-calendar/delete',{id:event.id,version:event.version});await loadCalendar();editEvent();});};
}
function showLoadError(error: unknown) { message(error instanceof Error ? error.message : 'Could not load your data.',true); }
async function loadMemory() {
  const data=await api<{facts:Fact[]}>('/api/memory/profile'); facts=data.facts; renderMemories();
}
function editMemory(fact?: Fact) {
  currentFact=fact; el('memory-editor-heading').textContent=fact?'Edit memory':'New memory';
  input('memory-kind').value=fact?.kind||'fact';input('memory-content').value=fact?.content||'';
  el('memory-delete').hidden=!fact; renderMemories();
}
function renderMemories() {
  const list=el('memory-list'); list.replaceChildren();
  const query=input('memory-search').value.toLocaleLowerCase();
  const filtered=facts.filter(f=>(f.content+' '+f.kind).toLocaleLowerCase().includes(query));
  for (const fact of filtered) {
    const item=button('',()=>editMemory(fact),'personal-item');item.classList.toggle('selected',fact.key===currentFact?.key);
    const meta=document.createElement('small');meta.textContent=fact.kind+(fact.manual?' · edited by you':'');
    const text=document.createElement('span');text.textContent=fact.content; item.append(meta,text);list.append(item);
  }
  if (!filtered.length) list.textContent=query?'No matching memories.':'Add something you want Jarvis to remember.';
}
async function loadCalendar() {
  const seq=++loading;
  const next=new Date(month.getFullYear(),month.getMonth()+1,1);
  const data=await api<{events:EventRow[];timezone:string}>(`/api/local-calendar/events?start=${dateKey(month)}&end=${dateKey(next)}`);
  if (seq!==loading) return;
  events=data.events;el('calendar-zone').textContent=`Times in ${data.timezone}. Saved locally; no Google connection needed.`; renderCalendar();
}
function onDay(event: EventRow, day: string): boolean {
  return event.start.slice(0,10)<=day && (event.end.slice(0,10)>day || (event.end.slice(0,10)===day && !event.all_day && event.end.slice(11,16)>'00:00'));
}
function renderCalendar() {
  el('month-title').textContent=month.toLocaleDateString('en-GB',{month:'long',year:'numeric'});
  const grid=el('calendar-grid');grid.replaceChildren();
  for (let n=0;n<(month.getDay()+6)%7;n++) grid.append(document.createElement('span'));
  const count=new Date(month.getFullYear(),month.getMonth()+1,0).getDate();
  for (let d=1;d<=count;d++) {
    const day=dateKey(new Date(month.getFullYear(),month.getMonth(),d));
    const count=events.filter(e=>onDay(e,day)).length;
    const b=button(String(d),()=>{selectedDay=day;renderCalendar();editEvent();},'calendar-day');
    b.setAttribute('aria-label',`${day}${count?`, ${count} event${count===1?'':'s'}`:''}`); b.setAttribute('aria-pressed',String(day===selectedDay));
    b.classList.toggle('selected',day===selectedDay);b.classList.toggle('today',day===dateKey(new Date()));
    if (count) {const dot=document.createElement('small');dot.textContent='•';b.append(dot);}grid.append(b);
  }
  el('calendar-day-title').textContent=new Date(selectedDay+'T12:00:00').toLocaleDateString('en-GB',{day:'numeric',month:'long'});
  const list=el('event-list');list.replaceChildren();
  const rows=events.filter(e=>onDay(e,selectedDay));
  for (const event of rows) {
    const item=button('',()=>editEvent(event),'personal-item');
    const meta=document.createElement('small');meta.textContent=event.all_day?'All day':event.start.slice(11,16)+' – '+event.end.slice(11,16);
    const text=document.createElement('span');text.textContent=event.title;item.append(meta,text);list.append(item);
  }
  if (!rows.length) list.textContent='Nothing planned for this day.';
}
function editEvent(event?: EventRow) {
  currentEvent=event;el('event-editor-heading').textContent=event?'Edit event':'New event';
  input('event-title').value=event?.title||'';input('event-all-day').checked=event?.all_day||false;
  input('event-start').type=input('event-end').type=event?.all_day?'date':'datetime-local';
  input('event-start').value=event?.start.slice(0,event.all_day?10:16)||selectedDay+'T09:00';
  input('event-end').value=event?.all_day?shiftDay(event.end,-1):event?.end.slice(0,16)||selectedDay+'T10:00';
  el('event-end-label').textContent=event?.all_day?'Last day (included)':'End';
  input('event-location').value=event?.location||'';input('event-description').value=event?.description||'';el('event-delete').hidden=!event;
}
function changeMonth(delta: number) { month=new Date(month.getFullYear(),month.getMonth()+delta,1);selectedDay=dateKey(month);editEvent();void loadCalendar().catch(showLoadError); }
export async function openPersonalPanel(next: View) {
  if (!dialog) createDialog();
  view=next;
  if (!dialog.open) {previousFocus=document.activeElement as HTMLElement;dialog.showModal();}
  el('personal-heading').textContent=view==='memory'?'Your memory':'Your calendar';
  el('personal-memory').hidden=view!=='memory';el('personal-calendar').hidden=view!=='calendar';
  el('personal-memory-tab').setAttribute('aria-current',String(view==='memory'));el('personal-calendar-tab').setAttribute('aria-current',String(view==='calendar'));
  message('Loading…');
  try {if (view==='memory') {await loadMemory();editMemory();} else {await loadCalendar();editEvent();}message('');}
  catch (error) {showLoadError(error);}
}
