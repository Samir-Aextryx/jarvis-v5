/** Short confirmation messages at the bottom of the settings window. */
let timer: ReturnType<typeof setTimeout> | undefined;

export function showToast(message: string, ok = true) {
  const element = document.getElementById('settings-toast');
  if (!element) return;
  element.textContent = message;
  element.dataset.state = ok ? 'ok' : 'error';
  element.classList.add('show');
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => element.classList.remove('show'), ok ? 3200 : 6000);
}
