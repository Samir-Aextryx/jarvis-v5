#include <Arduino.h>
#include <SPI.h>
#include <TFT_eSPI.h>
#include <math.h>

TFT_eSPI tft;
int currentPage = 0;

// Farbpalette (RGB565 - Cyber Dark Theme)
const uint16_t BG     = 0x0842;
const uint16_t CARD   = 0x10A4;
const uint16_t EDGE   = 0x2127;
const uint16_t TEXT   = 0xEF7D;
const uint16_t MUTED  = 0x8C73;
const uint16_t BLUE   = 0x5CFF;
const uint16_t GREEN  = 0x4EBA;
const uint16_t AMBER  = 0xFE29;
const uint16_t PURPLE = 0xB49F;

// --- UI Basis-Komponenten (320 x 480 Hochformat) ---

void label(const String &text, int x, int y, uint16_t color = TEXT,
           int size = 1, uint8_t datum = TL_DATUM) {
  tft.setTextDatum(datum);
  tft.setTextColor(color);
  tft.setTextSize(size);
  tft.drawString(text, x, y, 1);
}

void card(int x, int y, int w, int h, int radius = 12) {
  tft.fillRoundRect(x, y + 3, w, h, radius, TFT_BLACK); // Schatten
  tft.fillRoundRect(x, y, w, h, radius, CARD);
  tft.drawRoundRect(x, y, w, h, radius, EDGE);
}

void pill(int x, int y, int w, int h, const String &text, uint16_t dotColor, uint16_t textColor = TEXT) {
  tft.fillRoundRect(x, y, w, h, h / 2, EDGE);
  tft.fillCircle(x + 9, y + (h / 2), 3, dotColor);
  label(text, x + 18, y + (h / 2), textColor, 1, ML_DATUM);
}

void drawHeader(const String &title) {
  tft.fillScreen(BG);
  tft.fillRoundRect(14, 16, 4, 22, 2, BLUE);
  label(title, 26, 18, TEXT, 2);
  tft.fillCircle(248, 27, 3, GREEN);
  label("ESP32", 258, 27, MUTED, 1, ML_DATUM);
  tft.drawFastHLine(14, 46, 292, EDGE);
}

void footer(const String &hint) {
  tft.drawFastHLine(14, 448, 292, EDGE);
  label(hint, 16, 462, MUTED, 1, ML_DATUM);
  label("MINI OS", 304, 462, MUTED, 1, MR_DATUM);
}

void icon(int cx, int cy, int kind, uint16_t color) {
  if (kind == 1) { // Uhr
    tft.drawCircle(cx, cy, 18, color);
    tft.drawCircle(cx, cy, 19, color);
    tft.drawLine(cx, cy, cx, cy - 11, color);
    tft.drawLine(cx, cy, cx + 9, cy + 5, color);
    tft.fillCircle(cx, cy, 2, color);
  } else if (kind == 2) { // Rechner
    tft.drawRoundRect(cx - 15, cy - 20, 30, 40, 4, color);
    tft.fillRoundRect(cx - 10, cy - 14, 20, 8, 2, color);
    for (int r = 0; r < 2; r++)
      for (int c = 0; c < 3; c++)
        tft.fillRoundRect(cx - 10 + c * 8, cy + r * 9, 5, 5, 1, color);
  } else if (kind == 3) { // Setup
    for (int i = 0; i < 3; i++) {
      int yy = cy - 12 + i * 12;
      tft.drawFastHLine(cx - 19, yy, 38, color);
      int xx = cx + (i == 1 ? 8 : -7);
      tft.fillCircle(xx, yy, 5, color);
      tft.fillCircle(xx, yy, 2, CARD);
    }
  } else { // Info
    tft.drawCircle(cx, cy, 19, color);
    tft.drawCircle(cx, cy, 18, color);
    tft.fillCircle(cx, cy - 9, 2, color);
    tft.fillRoundRect(cx - 2, cy - 2, 4, 14, 2, color);
  }
}

void drawAppCard(int x, int y, int kind, uint16_t color, const String &name, const String &subtitle) {
  card(x, y, 138, 142, 12);
  icon(x + 69, y + 42, kind, color);
  label(name, x + 69, y + 84, TEXT, 2, MC_DATUM);
  label(subtitle, x + 69, y + 108, MUTED, 1, MC_DATUM);
  tft.fillRoundRect(x + 49, y + 126, 40, 3, 1, color);
}

// --- App 0: Home Screen ---

void homeScreen() {
  currentPage = 0;
  drawHeader("Home");
  label("Hallo Samir", 16, 62, TEXT, 3);
  label("Deine Apps. Alles auf einen Blick.", 17, 96, MUTED, 1);

  // 2x2 Raster - perfekt fuer 320px Breite
  drawAppCard(14,  122, 1, BLUE,   "Uhr",     "ZEIT & DATUM");
  drawAppCard(168, 122, 2, GREEN,  "Rechner", "ZAHLEN");
  drawAppCard(14,  276, 3, AMBER,  "Setup",   "OPTIONEN");
  drawAppCard(168, 276, 4, PURPLE, "Info",    "SYSTEM");

  footer("Serial: 1=Uhr | 2=Calc | 3=Setup | 4=Info");
}

// --- App 1: Uhr Screen ---

static float lastHRad = -1, lastMRad = -1, lastSRad = -1;

void clockApp() {
  currentPage = 1;
  lastHRad = -1;
  drawHeader("Uhr & Datum");

  // Obere Karte: Analoge Vektoruhr
  card(14, 56, 292, 186, 14);
  pill(24, 66, 90, 18, "ANALOG", BLUE);

  int cx = 160, cy = 150, r = 68;
  tft.drawCircle(cx, cy, r, EDGE);
  tft.drawCircle(cx, cy, r - 1, EDGE);

  for (int a = 0; a < 360; a += 30) {
    float rad = (a - 90) * 0.01745329;
    int len = (a % 90 == 0) ? 8 : 4;
    int x1 = cx + cos(rad) * (r - 2);
    int y1 = cy + sin(rad) * (r - 2);
    int x2 = cx + cos(rad) * (r - 2 - len);
    int y2 = cy + sin(rad) * (r - 2 - len);
    tft.drawLine(x1, y1, x2, y2, (a % 90 == 0) ? TEXT : MUTED);
  }

  // Untere Karte: Digitales Dashboard
  card(14, 252, 292, 186, 14);
  pill(26, 264, 116, 20, "ESP32 CLOCK", GREEN);
  label("MEZ / UTC+1", 294, 274, MUTED, 1, MR_DATUM);

  // Sekundenbalken Hintergrund
  tft.fillRoundRect(26, 386, 268, 6, 3, EDGE);
  label("STATUS: ONLINE", 26, 412, MUTED, 1, ML_DATUM);
  label("ALARM: 06:45", 294, 412, AMBER, 1, MR_DATUM);

  footer("Serial: 0=Home | 2-4=Apps");
}

void updateClock(int h, int m, int s, const String &dateStr = "DI, 06. OKT 2026") {
  if (currentPage != 1) return;

  int cx = 160, cy = 150;

  // Alte Zeiger loeschen
  if (lastHRad >= 0) {
    tft.drawLine(cx, cy, cx + cos(lastHRad) * 36, cy + sin(lastHRad) * 36, CARD);
    tft.drawLine(cx, cy, cx + cos(lastMRad) * 52, cy + sin(lastMRad) * 52, CARD);
    tft.drawLine(cx, cy, cx + cos(lastSRad) * 58, cy + sin(lastSRad) * 58, CARD);
  }

  float sRad = (s * 6 - 90) * 0.01745329;
  float mRad = (m * 6 + s * 0.1 - 90) * 0.01745329;
  float hRad = ((h % 12) * 30 + m * 0.5 - 90) * 0.01745329;

  tft.drawLine(cx, cy, cx + cos(hRad) * 36, cy + sin(hRad) * 36, TEXT);
  tft.drawLine(cx + 1, cy, cx + cos(hRad) * 36 + 1, cy + sin(hRad) * 36, TEXT);
  tft.drawLine(cx, cy, cx + cos(mRad) * 52, cy + sin(mRad) * 52, BLUE);
  tft.drawLine(cx, cy + 1, cx + cos(mRad) * 52, cy + sin(mRad) * 52 + 1, BLUE);
  tft.drawLine(cx, cy, cx + cos(sRad) * 58, cy + sin(sRad) * 58, AMBER);

  tft.fillCircle(cx, cy, 4, TEXT);
  tft.fillCircle(cx, cy, 2, BLUE);

  lastHRad = hRad;
  lastMRad = mRad;
  lastSRad = sRad;

  // Digitalanzeige
  char timeBuf[9];
  snprintf(timeBuf, sizeof(timeBuf), "%02d:%02d", h, m);
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(TEXT, CARD);
  tft.setTextSize(5);
  tft.drawString(timeBuf, 26, 296);

  // Sekunden-Pill
  char secBuf[5];
  snprintf(secBuf, sizeof(secBuf), ":%02d", s);
  tft.fillRoundRect(236, 302, 58, 28, 6, EDGE);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(AMBER, EDGE);
  tft.setTextSize(2);
  tft.drawString(secBuf, 265, 316);

  // Datum
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(MUTED, CARD);
  tft.setTextSize(2);
  tft.drawString(dateStr, 26, 354);

  // Sekundenbalken
  int barWidth = map(s, 0, 59, 0, 268);
  if (barWidth > 0) tft.fillRoundRect(26, 386, barWidth, 6, 3, BLUE);
  if (barWidth < 268) tft.fillRoundRect(26 + barWidth, 386, 268 - barWidth, 6, 3, EDGE);
}

// --- App 2: Rechner Screen ---

void calcApp() {
  currentPage = 2;
  drawHeader("Rechner");

  // Display
  card(14, 56, 292, 54, 8);
  label("42 x 8 = 336", 294, 83, GREEN, 2, MR_DATUM);

  // Tastenfeld (Grid 4x4)
  const char* keys[4][4] = {
    {"7", "8", "9", "/"},
    {"4", "5", "6", "x"},
    {"1", "2", "3", "-"},
    {"C", "0", "=", "+"}
  };

  int startX = 14, startY = 120;
  int btnW = 62, btnH = 64;
  int gapX = 14, gapY = 12;

  for (int r = 0; r < 4; r++) {
    for (int c = 0; c < 4; c++) {
      int bx = startX + c * (btnW + gapX);
      int by = startY + r * (btnH + gapY);
      uint16_t btnColor = (c == 3 || (r == 3 && c == 2)) ? GREEN : TEXT;
      if (r == 3 && c == 0) btnColor = AMBER;

      card(bx, by, btnW, btnH, 8);
      label(keys[r][c], bx + (btnW / 2), by + (btnH / 2), btnColor, 2, MC_DATUM);
    }
  }

  footer("Serial: 0=Home | 1=Uhr | 3=Setup | 4=Info");
}

// --- App 3: Setup Screen ---

void settingsApp() {
  currentPage = 3;
  drawHeader("Einstellungen");

  card(14, 56, 292, 380, 16);

  // WLAN
  label("WLAN Verbindung", 28, 74, TEXT, 2);
  label("Wokwi-GUEST", 28, 96, MUTED, 1);
  pill(194, 76, 98, 24, "ONLINE", GREEN);
  tft.drawFastHLine(28, 126, 264, EDGE);

  // Helligkeit
  label("Display Helligkeit", 28, 142, TEXT, 2);
  label("100% Maximal", 28, 164, MUTED, 1);
  tft.fillRoundRect(28, 186, 264, 12, 6, EDGE);
  tft.fillRoundRect(28, 186, 220, 12, 6, BLUE);
  tft.drawFastHLine(28, 220, 264, EDGE);

  // Bluetooth
  label("Bluetooth BLE", 28, 236, TEXT, 2);
  label("Sichtbar fuer Geraete", 28, 258, MUTED, 1);
  pill(194, 238, 98, 24, "BEREIT", BLUE);
  tft.drawFastHLine(28, 288, 264, EDGE);

  // Theme
  label("Design Theme", 28, 304, TEXT, 2);
  label("Cyberpunk Dark Mode", 28, 326, MUTED, 1);
  pill(194, 306, 98, 24, "DARK", PURPLE);

  footer("Serial: 0=Home | 1=Uhr | 2=Rechner | 4=Info");
}

// --- App 4: Info Screen ---

void infoApp() {
  currentPage = 4;
  drawHeader("System Info");

  // Kachel 1: Chip
  card(14, 56, 292, 82, 12);
  pill(26, 68, 80, 20, "CHIP", BLUE);
  label("ESP32-D0WD", 26, 98, TEXT, 2);
  label("Dual Core 240 MHz", 170, 98, MUTED, 1);

  // Kachel 2: Flash
  card(14, 148, 292, 82, 12);
  pill(26, 160, 80, 20, "FLASH", AMBER);
  label("4 MB SPI Flash", 26, 190, TEXT, 2);
  label("Speed: 80 MHz", 170, 190, MUTED, 1);

  // Kachel 3: RAM
  card(14, 240, 292, 82, 12);
  pill(26, 252, 80, 20, "RAM", GREEN);
  char heapBuf[32];
  snprintf(heapBuf, sizeof(heapBuf), "%d KB frei", (int)(ESP.getFreeHeap() / 1024));
  label(heapBuf, 26, 282, TEXT, 2);
  label("Dynamischer Heap", 170, 282, MUTED, 1);

  // Kachel 4: Uptime
  card(14, 332, 292, 82, 12);
  pill(26, 344, 80, 20, "UPTIME", PURPLE);
  char upBuf[32];
  unsigned long sec = millis() / 1000;
  snprintf(upBuf, sizeof(upBuf), "%02lu:%02lu min", sec / 60, sec % 60);
  label(upBuf, 26, 374, TEXT, 2);
  label("Seit Start", 170, 374, MUTED, 1);

  footer("Serial: 0=Home | 1=Uhr | 2=Rechner | 3=Setup");
}

// --- Setup & Hauptschleife ---

void setup() {
  Serial.begin(115200);
  tft.init();
  tft.setRotation(0); // 320x480 Hochformat (Portrait)

  Serial.println("\n========================");
  Serial.println("   ESP32 MINI OS 1.0    ");
  Serial.println("========================");
  Serial.println("Befehle im Serial Monitor:");
  Serial.println(" 0 = Home");
  Serial.println(" 1 = Uhr & Datum");
  Serial.println(" 2 = Rechner");
  Serial.println(" 3 = Einstellungen");
  Serial.println(" 4 = System Info");
  Serial.println("========================\n");

  homeScreen();
}

unsigned long lastTick = 0;
int simH = 13, simM = 51, simS = 0;

void loop() {
  if (Serial.available()) {
    char ch = Serial.read();
    if (ch == '0') homeScreen();
    else if (ch == '1') clockApp();
    else if (ch == '2') calcApp();
    else if (ch == '3') settingsApp();
    else if (ch == '4') infoApp();
  }

  if (currentPage == 1 && millis() - lastTick >= 1000) {
    lastTick = millis();
    if (++simS >= 60) {
      simS = 0;
      if (++simM >= 60) {
        simM = 0;
        if (++simH >= 24) simH = 0;
      }
    }
    updateClock(simH, simM, simS, "DI, 06. OKT 2026");
  }
}
