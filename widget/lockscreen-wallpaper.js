// Year Progress Wallpaper v31 - Wallpapers, gradients and massive rework and update
// by agaragou
// https://github.com/agaragou/LockScreen-Calendar-ShortCut
//
// + News brief card below the calendar (section 8 in CONFIG), fed by
//   summary.json from the daily tech & security brief pipeline in this repo.
const CONFIG = {
  // --- 1. GENERAL & APPEARANCE ---
  monthsToShow: 3,        // 12 = Year, 3 = Quarter, 1 = Month
  monthsPerRow: 3,         // Standard is 3
  monthOffset: -1,          // Start from 0 = Current, -1 = Previous, 1 = Next
  contentScale: 1.0,       // Global Scale Multiplier (>1.0 bigger, <1.0 smaller)

  // Day & Dot Settings
  showDayNumbers: true,   // true = numbers, false = dots
  firstDayOfWeek: 1,       // 0 = Sunday, 1 = Monday
  highlightWeekends: true,
  dimPastDays: true,       // If true, past days are 30% opacity
  dayFontSizeMultiplier: 1.1, // Font size for days
  dotSizeMultiplier: 1.1,  // Only applies if showDayNumbers is false

  // --- 2. BACKGROUND SETTINGS ---
  // Custom Wallpaper (Photo from Shortcuts)
  showWallpaper: true,     // Priority 1: Use photo if provided
  overlayOpacity: 0.3,     // Darken photo (0.0 - 1.0)

  // Gradient (Priority 2: Used if no photo or showWallpaper=false)
  useGradient: true,
  gradientColors: ["#0F2027", "#203A43", "#2C5364"], // Example: "Moonlit Asteroid"

  // Container (Card behind calendar for better visibility on wallpaper)
  showContainer: true,
  containerOpacity: 0.60,
  containerRadius: 15,

  // --- 3. LAYOUT & WIDGETS ---
  // Avoid Widget Areas?
  widgetsTop: false,
  topWidgetsPadding: 0.36,    // 0.36 = 36% of screen height
  widgetsBottom: true,
  bottomWidgetsPadding: 0.17, // 0.17 = 17% of screen height

  // --- 4. DATA & CALENDARS ---
  calendarPrefix: "",
  // specificCalendarNames: ["Work", "Home"], 
  specificCalendarNames: [],

  // Manual Dates ["MM-DD"]
  manualSignificantDates: [],

  // Event Sorting
  sortByName: true, // true = Alphabetical, false = System order

  // --- 5. STATISTICS ---
  showStats: true,
  statsMode: "events", // "progress" or "events" // year progress or # events today

  // --- 6. COLORS ---
  colors: {
    bg: new Color("#000000"),
    pastDay: new Color("#ffffff", 0.95),
    futureDay: new Color("#c3c3c3"),
    today: new Color("#ff3b30"),
    significant: new Color("#FFD60A"),
    text: new Color("#98989d"),
    stats: new Color("#ff9f0a"),
    weekend: new Color("#515155ff")
  },

  // --- 7. INTERNAL RATIOS ---
  ratios: {
    topPadding: 0.335,
    spacing: 30.5,
    radius: 0.3,
    monthGap: 1.9,
    colGap: 1.6
  },

  // --- 8. NEWS BRIEF (card below the calendar) ---
  // Reads summary.json written nightly by the tech & security brief pipeline.
  showNews: true,
  newsUrl: "https://gist.githubusercontent.com/aditya06121/7028a3c2b27df52a52ab260299ec00cd/raw/summary.json",
  newsTimeoutSeconds: 10,
  newsMaxFontSize: 15,     // Points start at this size and shrink until they fit...
  newsMinFontSize: 9,      // ...but never below this (then the last points are dropped)
  newsStaleHours: 36,      // Older than this = nightly run probably failed
  newsTextColor: new Color("#ffffff", 0.92)
};

// --- 1. AUTO-DETECT SCREEN SIZE ---
const screen = Device.screenSize();
const width = screen.width;
const height = screen.height;

// --- LAYOUT CALCULATIONS ---
let startY = CONFIG.widgetsTop ? (height * CONFIG.topWidgetsPadding) : (height * CONFIG.ratios.topPadding);

// Stats & Calendar Limits
let fontSizeStats = (width * 0.028); // FIXED size, ignored by contentScale
const statsHeight = CONFIG.showStats ? (fontSizeStats * 4) : 0;

let calendarLimitY = CONFIG.widgetsBottom
  ? height * (1 - CONFIG.bottomWidgetsPadding)
  : height - statsHeight;

if (CONFIG.widgetsBottom) startY = height * 0.3; // Specific override if bottom widgets exist

const calendarAvailableHeight = calendarLimitY - startY;

// Calendar sizing (will be auto-shrunk if needed)
let dotSpacing = (width / CONFIG.ratios.spacing) * CONFIG.contentScale;
let dotRadius = (dotSpacing * CONFIG.ratios.radius) * CONFIG.dotSizeMultiplier;
let monthGap = dotSpacing * CONFIG.ratios.monthGap;
let colGap = dotSpacing * CONFIG.ratios.colGap;
let fontSizeMonth = (width * 0.022) * CONFIG.contentScale;
let fontSizeDay = (width * 0.022) * CONFIG.dayFontSizeMultiplier * CONFIG.contentScale;

// 4. SCALE DOWN if exceeding limits
const rows = Math.ceil(CONFIG.monthsToShow / CONFIG.monthsPerRow);
const monthsCols = CONFIG.monthsPerRow;

const singleRowHeightInitial = (6 * dotSpacing) + (fontSizeMonth * 2) + monthGap;
const totalContentHeight = (rows * singleRowHeightInitial);

// Calculate Total Width (Approximation for auto-scale check)
const oneMonthWidth = (6 * dotSpacing) + (dotRadius * 2);
const totalContentWidth = (monthsCols * oneMonthWidth) + ((monthsCols - 1) * colGap);

// Determine limiting factors
const heightScale = (totalContentHeight > calendarAvailableHeight) ? (calendarAvailableHeight / totalContentHeight) : 1;
const safeWidth = width * 0.94; // Keep 3% margin on sides
const widthScale = (totalContentWidth > safeWidth) ? (safeWidth / totalContentWidth) : 1;

const finalAutoScale = Math.min(heightScale, widthScale);

if (finalAutoScale < 1.0) {
  // Apply scale to ALL calendar dimensions, but NOT stats
  dotSpacing *= finalAutoScale;
  dotRadius *= finalAutoScale;
  monthGap *= finalAutoScale;
  colGap *= finalAutoScale;
  fontSizeMonth *= finalAutoScale;
  fontSizeDay *= finalAutoScale;
  // fontSizeStats remains untouched
}

const PADDING_TOP = startY;
const DOT_SPACING = dotSpacing;
const DOT_RADIUS = dotRadius;
const MONTH_GAP = monthGap;
const COL_GAP = colGap;
const SINGLE_ROW_HEIGHT = (6 * DOT_SPACING) + (fontSizeMonth * 2) + MONTH_GAP;

// --- 2. AUTO-SCAN CALENDARS ---
const date = new Date();
const currentYear = date.getFullYear();
const currentMonth = date.getMonth();
const currentDay = date.getDate();

async function fetchAutoCalendars() {
  let calendarsList = [];

  // Calculate range based on monthsToShow
  // We need to cover enough future time
  const futureYears = Math.ceil(CONFIG.monthsToShow / 12);
  const startOfRange = new Date(currentYear, 0, 1);
  const endOfRange = new Date(currentYear + futureYears, 11, 31, 23, 59, 59);

  try {
    const allCalendars = await Calendar.forEvents();

    let targetCalendars;
    if (CONFIG.specificCalendarNames && CONFIG.specificCalendarNames.length > 0) {
      targetCalendars = allCalendars.filter(c => CONFIG.specificCalendarNames.includes(c.title));
      // Sort by order in specificCalendarNames (Priority: First in list = Highest Priority)
      targetCalendars.sort((a, b) => {
        return CONFIG.specificCalendarNames.indexOf(a.title) - CONFIG.specificCalendarNames.indexOf(b.title);
      });
    } else {
      targetCalendars = allCalendars.filter(c => c.title.startsWith(CONFIG.calendarPrefix));
      // Sort by name if enabled (only for prefix mode)
      if (CONFIG.sortByName) {
        targetCalendars.sort((a, b) => a.title.localeCompare(b.title));
      }
    }

    for (let cal of targetCalendars) {
      const events = await CalendarEvent.between(startOfRange, endOfRange, [cal]);

      calendarsList.push({
        name: cal.title,
        color: cal.color, // GET COLOR DIRECTLY FROM IOS
        events: events.map(e => ({
          start: e.startDate,
          end: e.endDate
        }))
      });
    }
  } catch (e) { console.log("Error: " + e.message); }

  return calendarsList;
}

const activeCalendarsData = await fetchAutoCalendars();

// --- 2b. NEWS BRIEF DATA ---
// Fetch summary.json; on failure fall back to the last good copy so the card
// still shows something offline. Never throws: no data = no card.
async function fetchNewsBrief() {
  if (!CONFIG.showNews) return null;
  const fm = FileManager.local();
  const cachePath = fm.joinPath(fm.documentsDirectory(), "tech-brief-cache.json");

  try {
    const req = new Request(`${CONFIG.newsUrl}?t=${Date.now()}`); // cache-buster
    req.timeoutInterval = CONFIG.newsTimeoutSeconds;
    const data = await req.loadJSON();
    if (data && (Array.isArray(data.lockscreen) || typeof data.lockscreen === "string")) {
      fm.writeString(cachePath, JSON.stringify(data));
      return data;
    }
  } catch (e) { console.log("News fetch error: " + e.message); }

  try {
    if (fm.fileExists(cachePath)) return JSON.parse(fm.readString(cachePath));
  } catch (e) { console.log("News cache error: " + e.message); }
  return null;
}

const newsData = await fetchNewsBrief();

// --- BACKGROUND DRAWING ---
let bgImage = null;
if (args.images && args.images.length > 0) bgImage = args.images[0];
else if (args.shortcutParameter) {
  if (args.shortcutParameter.size) bgImage = args.shortcutParameter;
  else if (typeof args.shortcutParameter === "string") {
    let path = args.shortcutParameter.replace("file://", "");
    if (FileManager.local().fileExists(path)) bgImage = FileManager.local().readImage(path);
  }
}

// --- DRAWING SETUP ---
const ctx = new DrawContext();
ctx.size = new Size(width, height);
ctx.respectScreenScale = true;
ctx.opaque = true;

// Check if we should draw the image (Priority 1)
if (CONFIG.showWallpaper && bgImage) {
  // 1. Draw image with Aspect Fill (Crop to fit)
  const imgSize = bgImage.size;
  const imgAspect = imgSize.width / imgSize.height;
  const screenAspect = width / height;

  let drawRect;
  if (imgAspect > screenAspect) {
    // Image is wider than screen: scale to height, center width
    const newWidth = height * imgAspect;
    const xOffset = (newWidth - width) / 2;
    drawRect = new Rect(-xOffset, 0, newWidth, height);
  } else {
    // Image is taller than screen: scale to width, center height
    const newHeight = width / imgAspect;
    const yOffset = (newHeight - height) / 2;
    drawRect = new Rect(0, -yOffset, width, newHeight);
  }
  ctx.drawImageInRect(bgImage, drawRect);

  // 2. Draw Overlay (to make text readable)
  if (CONFIG.overlayOpacity > 0) {
    ctx.setFillColor(new Color("#000000", CONFIG.overlayOpacity));
    ctx.fillRect(new Rect(0, 0, width, height));
  }
} else {
  // Default: Check for Gradient or Solid Color
  if (CONFIG.useGradient && CONFIG.gradientColors && CONFIG.gradientColors.length > 1) {
    // Scriptable's DrawContext doesn't have drawGradient directly, 
    // so we use a WebView with HTML5 Canvas to generate the gradient image reliably.
    // This avoids race conditions with "captureSnapshot".
    const gradientColorsString = CONFIG.gradientColors.map(c => `"${c}"`).join(", ");

    const html = `
      <html>
      <body>
        <canvas id="gradCanvas" width="${width}" height="${height}"></canvas>
        <script>
          const canvas = document.getElementById('gradCanvas');
          const ctx = canvas.getContext('2d');
          const grad = ctx.createLinearGradient(0, 0, ${width}, ${height}); // Diagonal
          const colors = [${gradientColorsString}];
          
          colors.forEach((c, i) => {
            grad.addColorStop(i / (colors.length - 1), c);
          });
          
          ctx.fillStyle = grad;
          ctx.fillRect(0, 0, ${width}, ${height});
          
          // Return Base64
          completion(canvas.toDataURL("image/png"));
        </script>
      </body>
      </html>`;

    try {
      const wv = new WebView();
      await wv.loadHTML(html);
      const base64String = await wv.evaluateJavaScript("canvas.toDataURL()");

      // Clean up the base64 string (remove data:image/png;base64,) and load
      const imgData = Data.fromBase64String(base64String.split(",")[1]);
      const gradientImage = Image.fromData(imgData);

      ctx.drawImageInRect(gradientImage, new Rect(0, 0, width, height));
    } catch (e) {
      console.log("Gradient Error: " + e.message);
      ctx.setFillColor(new Color(CONFIG.gradientColors[0]));
      ctx.fillRect(new Rect(0, 0, width, height));
    }
  } else {
    // Solid Color
    ctx.setFillColor(CONFIG.colors.bg);
    ctx.fillRect(new Rect(0, 0, width, height));
  }
}

const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function getDayColor(year, month, day) {
  const monthStr = (month + 1).toString().padStart(2, '0');
  const dayStr = day.toString().padStart(2, '0');
  const dateString = `${monthStr}-${dayStr}`;

  // Calculate absolute day values for comparison (year * 10000 + month * 100 + day)
  const absCurrent = currentYear * 10000 + currentMonth * 100 + currentDay;
  const absTarget = year * 10000 + month * 100 + day;

  const isPast = absTarget < absCurrent;
  const isToday = absTarget === absCurrent;

  // Helper to dim color if needed
  const finalizeColor = (c) => {
    if (CONFIG.dimPastDays && isPast) {
      return new Color(c.hex, 0.5); // 30% opacity for past days
    }
    return c;
  };

  // 1. Priority: Today
  if (isToday) return CONFIG.colors.today;

  // 2. Priority: Manual Dates
  if (CONFIG.manualSignificantDates.includes(dateString)) return finalizeColor(CONFIG.colors.significant);

  const dayStart = new Date(year, month, day, 0, 0, 0);
  const dayEnd = new Date(year, month, day, 23, 59, 59);

  // 3. Priority: Calendars
  for (let calData of activeCalendarsData) {
    for (let event of calData.events) {
      if (event.start <= dayEnd && event.end >= dayStart) {
        return finalizeColor(calData.color);
      }
    }
  }

  // 4. Weekend
  const dayOfWeek = new Date(year, month, day).getDay();
  if (CONFIG.highlightWeekends && (dayOfWeek === 0 || dayOfWeek === 6)) {
    return finalizeColor(CONFIG.colors.weekend);
  }

  // 5. Background
  if (isPast) {
    if (CONFIG.dimPastDays) return finalizeColor(CONFIG.colors.futureDay); // "As it was" (dimmed future color)
    return CONFIG.colors.pastDay;
  }
  return CONFIG.colors.futureDay;
}

const monthBlockWidth = (6 * DOT_SPACING) + (DOT_RADIUS * 2);
const totalCalendarWidth = (CONFIG.monthsPerRow * monthBlockWidth) + ((CONFIG.monthsPerRow - 1) * COL_GAP);
const startX = (width - totalCalendarWidth) / 2;

// --- CONTAINER GEOMETRY (always computed; the news card is placed below it) ---
const containerPadding = DOT_SPACING * 0.8;
const containerX = startX - containerPadding;
const containerW = totalCalendarWidth + (containerPadding * 2);
let containerY, containerH;
{
  // Calculate visual boundaries for symmetric padding
  const totalRows = Math.ceil(CONFIG.monthsToShow / CONFIG.monthsPerRow);

  // Find absolute weeks in last row
  const lastRowStartIndex = (totalRows - 1) * CONFIG.monthsPerRow;
  const lastRowEndIndex = Math.min(lastRowStartIndex + CONFIG.monthsPerRow, CONFIG.monthsToShow);
  let maxWeeksInLastRow = 0;

  for (let idx = lastRowStartIndex; idx < lastRowEndIndex; idx++) {
    let targetMonthIndex = (currentMonth + CONFIG.monthOffset + idx);
    let year = currentYear + Math.floor(targetMonthIndex / 12);
    let month = ((targetMonthIndex % 12) + 12) % 12;

    // Week calculation
    const firstDay = new Date(year, month, 1).getDay();
    const daysInMonth = 32 - new Date(year, month, 32).getDate();
    const offset = (firstDay - CONFIG.firstDayOfWeek + 7) % 7;
    let w = Math.ceil((daysInMonth + offset) / 7);
    if (w > maxWeeksInLastRow) maxWeeksInLastRow = w;
  }
  if (maxWeeksInLastRow < 4) maxWeeksInLastRow = 4;

  // Visual Top: Above Header
  const headerVisualOffset = (DOT_SPACING * 1.2);
  const contentTopY = PADDING_TOP - headerVisualOffset;

  // Visual Bottom: Below last row dots
  const lastRowY = PADDING_TOP + ((totalRows - 1) * SINGLE_ROW_HEIGHT);
  const dotsHeight = ((maxWeeksInLastRow - 1) * DOT_SPACING) + (DOT_RADIUS * 1.2);
  const contentBottomY = lastRowY + dotsHeight;

  containerY = contentTopY - containerPadding;
  containerH = (contentBottomY - contentTopY) + (containerPadding * 2);
}

// --- DRAW CONTAINER (Optional) ---
if (CONFIG.showContainer) {
  const path = new Path();
  path.addRoundedRect(new Rect(containerX, containerY, containerW, containerH), CONFIG.containerRadius, CONFIG.containerRadius);
  ctx.setFillColor(new Color("#000000", CONFIG.containerOpacity));
  ctx.addPath(path);
  ctx.fillPath();
}

// Loop for dynamic number of months

for (let i = CONFIG.monthOffset; i < CONFIG.monthOffset + CONFIG.monthsToShow; i++) {
  // Logic to handle month/year overflow
  let targetMonthIndex = (currentMonth + i);

  // Correction for negative indices (if we supported past months properly in the loop)
  // Standard math for modulo with negatives
  targetMonthIndex = ((targetMonthIndex % 12) + 12) % 12;

  let targetYear = currentYear + Math.floor((currentMonth + i) / 12);

  // Adjust i for grid placement if we started with negative offset
  let gridIndex = i - CONFIG.monthOffset;
  const colIndex = gridIndex % CONFIG.monthsPerRow;
  const rowIndex = Math.floor(gridIndex / CONFIG.monthsPerRow);

  const blockX = startX + (colIndex * (monthBlockWidth + COL_GAP));
  const rowHeight = SINGLE_ROW_HEIGHT;
  const blockY = PADDING_TOP + (rowIndex * rowHeight);

  ctx.setTextColor(CONFIG.colors.text);
  ctx.setFont(Font.boldSystemFont(fontSizeMonth));
  ctx.setTextAlignedLeft();

  // Header Text
  let headerText = monthNames[targetMonthIndex];
  // Add year if it's different from start or if it's Jan
  if (targetYear !== currentYear || (targetMonthIndex === 0 && i !== 0)) {
    headerText += ` '${targetYear.toString().slice(-2)}`;
  }

  ctx.drawText(headerText, new Point(blockX - (DOT_SPACING * 0.1), blockY - (DOT_SPACING * 1.2)));

  const daysInMonth = new Date(targetYear, targetMonthIndex + 1, 0).getDate();
  let firstDayWeek = new Date(targetYear, targetMonthIndex, 1).getDay();
  // Calculate empty slots at start of month
  // 0 = Sunday, 1 = Monday, etc.
  let startOffset = (firstDayWeek - CONFIG.firstDayOfWeek + 7) % 7;

  for (let d = 1; d <= daysInMonth; d++) {
    const dayIndex = (startOffset + d - 1);
    const gridX = dayIndex % 7;
    const gridY = Math.floor(dayIndex / 7);
    const dotX = blockX + (gridX * DOT_SPACING);
    const dotY = blockY + (gridY * DOT_SPACING);

    // Pass targetYear to getDayColor to handle year boundaries correctly
    const fillColor = getDayColor(targetYear, targetMonthIndex, d);
    if (CONFIG.showDayNumbers) {
      ctx.setTextColor(fillColor);
      ctx.setFont(Font.boldSystemFont(fontSizeDay * 0.9)); // Slightly smaller for numbers
      ctx.setTextAlignedCenter();
      // Center text in the grid cell
      // Used DOT_SPACING as width/height to center in the cell space
      const textRect = new Rect(dotX - (DOT_SPACING * 0.1), dotY - (DOT_SPACING * 0.15), DOT_SPACING * 1.2, DOT_SPACING);
      ctx.drawTextInRect(d.toString(), textRect);
    } else {
      ctx.setFillColor(fillColor);
      ctx.fillEllipse(new Rect(dotX, dotY, DOT_RADIUS * 2, DOT_RADIUS * 2));
    }
  }
}

// --- STATS ---
if (CONFIG.showStats) {
  // Calculate dynamic stats position based on total rows
  const totalRows = Math.ceil(CONFIG.monthsToShow / CONFIG.monthsPerRow);

  // Position stats - PINNED TO ABSOLUTE BOTTOM
  // We use the full HEIGHT (ignoring widget padding)
  const statsY = height - (fontSizeStats * 3.5); // Fixed at bottom
  const statsRect = new Rect(0, statsY, width, fontSizeStats * 3);

  ctx.setTextAlignedCenter();
  ctx.setFont(Font.boldSystemFont(fontSizeStats));
  ctx.setTextColor(CONFIG.colors.stats);
  if (CONFIG.statsMode === "events") {
    let eventCount = 0;
    const todayStart = new Date(currentYear, currentMonth, currentDay, 0, 0, 0);
    const todayEnd = new Date(currentYear, currentMonth, currentDay, 23, 59, 59);

    for (let calData of activeCalendarsData) {
      for (let e of calData.events) {
        if (e.start <= todayEnd && e.end >= todayStart) {
          eventCount++;
        }
      }
    }
    const eventWord = (eventCount === 1) ? "event" : "events";
    ctx.drawTextInRect(`${eventCount} ${eventWord} today`, statsRect);
  } else {
    const startOfYear = new Date(currentYear, 0, 1);
    const endOfYear = new Date(currentYear + 1, 0, 1);
    const totalDays = (endOfYear - startOfYear) / (1000 * 60 * 60 * 24);
    const daysPassed = Math.ceil(Math.abs(date - startOfYear) / (1000 * 60 * 60 * 24));
    const daysLeft = Math.floor(totalDays - daysPassed);
    const percentPassed = Math.floor((daysPassed / totalDays) * 100);
    ctx.drawTextInRect(`${daysLeft} days left  •  ${percentPassed}%`, statsRect);
  }
}

// --- NEWS BRIEF CARD ---
// Scriptable can't measure text, so lines are wrapped using the advance widths
// of the iOS system font (SF Pro Text, Regular) for ASCII, in em units.
const SF_WIDTHS = [0.281,0.311,0.478,0.63,0.63,0.926,0.711,0.297,0.382,0.382,0.472,0.63,0.297,0.472,0.297,0.305,0.63,0.464,0.603,0.627,0.643,0.618,0.636,0.569,0.638,0.636,0.297,0.297,0.63,0.63,0.63,0.513,0.918,0.674,0.658,0.715,0.727,0.596,0.572,0.746,0.743,0.268,0.538,0.659,0.568,0.874,0.743,0.772,0.636,0.772,0.654,0.637,0.634,0.738,0.674,0.968,0.679,0.656,0.661,0.382,0.305,0.382,0.63,0.584,0.5,0.552,0.615,0.56,0.614,0.572,0.362,0.61,0.588,0.246,0.246,0.543,0.253,0.87,0.583,0.591,0.611,0.61,0.381,0.523,0.363,0.583,0.542,0.774,0.524,0.543,0.539,0.382,0.259,0.382,0.63]; // chars 32-126
const NEWS_LINE_HEIGHT = 1.3;  // line height as a fraction of font size
const NEWS_WIDTH_SAFETY = 0.96; // fill at most 96% of the width (rendering differences)

// Estimated width in points of `text` at `size`, incl. iOS's automatic extra
// letter spacing at small sizes (~+0.06pt/char at 11pt, ~+0.2pt at 8.5pt).
function textWidth(text, size) {
  const tracking = Math.max(0, (12 - size) * 0.06);
  let w = 0;
  for (const ch of text) {
    const code = ch.codePointAt(0);
    if (code >= 32 && code <= 126) w += SF_WIDTHS[code - 32] * size;
    else if (code === 0xFE0F || code === 0x200D) continue;  // emoji modifiers: no width
    else if (code > 0x2190) w += 1.3 * size;                 // symbols & emoji (⚠️, 📰)
    else w += 0.65 * size;                                    // accents, dashes, “quotes”
    w += tracking;
  }
  return w;
}

function wrapText(text, maxWidth, size) {
  const lines = [];
  let line = "";
  for (let word of text.split(/\s+/).filter(w => w.length > 0)) {
    // Hard-split words longer than a full line (e.g. URLs)
    while (textWidth(word, size) > maxWidth && word.length > 1) {
      if (line) { lines.push(line); line = ""; }
      let cut = word.length - 1;
      while (cut > 1 && textWidth(word.slice(0, cut), size) > maxWidth) cut--;
      lines.push(word.slice(0, cut));
      word = word.slice(cut);
    }
    if (!line) line = word;
    else if (textWidth(line + " " + word, size) <= maxWidth) line += " " + word;
    else { lines.push(line); line = word; }
  }
  if (line) lines.push(line);
  return lines;
}

// Points come as an array (current pipeline) or, from older data, one paragraph.
function newsPoints(data) {
  const raw = Array.isArray(data.lockscreen)
    ? data.lockscreen
    : String(data.lockscreen || "").split(/(?<=[.!?])\s+(?=[A-Z0-9⚠])/);
  return raw.map(p => String(p).trim()).filter(p => p.length > 0).map(p => {
    const warn = p.startsWith("⚠");
    return { warn, text: warn ? p.replace(/^⚠\uFE0F?\s*/, "") : p };
  });
}

// Lay out points as bullets with a hanging indent; the gap between points is
// part of the height. Returns null if they don't fit.
function layoutPoints(points, boxWidth, maxHeight, size) {
  const indent = size * 1.7;  // bullet column (fits the ⚠️ emoji)
  const lineH = size * NEWS_LINE_HEIGHT;
  const gap = size * 0.45;
  const items = points.map(p => ({ warn: p.warn, lines: wrapText(p.text, (boxWidth - indent) * NEWS_WIDTH_SAFETY, size) }));
  const totalLines = items.reduce((n, it) => n + it.lines.length, 0);
  const height = (totalLines * lineH) + (Math.max(items.length - 1, 0) * gap);
  return height <= maxHeight ? { size, indent, lineH, gap, items, height } : null;
}

// Largest font size (stepping down by 0.5) at which all points fit; at the
// minimum size, drop the least important (last) points until they fit.
function fitPoints(points, boxWidth, maxHeight) {
  for (let size = CONFIG.newsMaxFontSize; size >= CONFIG.newsMinFontSize; size -= 0.5) {
    const layout = layoutPoints(points, boxWidth, maxHeight, size);
    if (layout) return layout;
  }
  for (let n = points.length - 1; n >= 1; n--) {
    const layout = layoutPoints(points.slice(0, n), boxWidth, maxHeight, CONFIG.newsMinFontSize);
    if (layout) return layout;
  }
  return null;
}

function newsAgeHours(data) {
  const t = Date.parse(data.generated_at || "");
  return isNaN(t) ? null : (Date.now() - t) / (1000 * 60 * 60);
}

if (CONFIG.showNews && newsData) {
  const pad = containerPadding;
  const cardX = containerX;
  const cardW = containerW;
  const cardTop = containerY + containerH + pad;

  // Bottom limit: above the iOS widget/flashlight zone, or above the stats line
  const statsTop = CONFIG.showStats ? height - (fontSizeStats * 3.5) : height;
  const cardBottomLimit = CONFIG.widgetsBottom
    ? height * (1 - CONFIG.bottomWidgetsPadding)
    : statsTop - pad;

  // Header: "📰 27 Oct" left, KEV counts / stale / error right
  const headerSize = Math.max(fontSizeMonth * 1.3, 10.5);
  const headerH = headerSize * NEWS_LINE_HEIGHT;
  const isError = newsData.status === "error";
  const age = newsAgeHours(newsData);
  const isStale = age !== null && age > CONFIG.newsStaleHours;

  let headerLeft = isError ? "⚠️ Brief failed" : `📰 ${newsData.date_ist || "Brief"}`;
  let headerRight = "";
  if (isStale) {
    headerRight = `stale · ${age >= 48 ? Math.floor(age / 24) + "d" : Math.floor(age) + "h"} old`;
  } else if (!isError) {
    const parts = [];
    if (newsData.new_kev_count > 0) parts.push(`⚠️ ${newsData.new_kev_count} new KEV`);
    if (newsData.exploited_in_news_count > 0) parts.push(`${newsData.exploited_in_news_count} exploited`);
    headerRight = parts.join(" · ");
  }

  // Points, auto-fitted to the remaining space
  const textW = cardW - (pad * 2);
  const bodyGap = headerSize * 0.6;
  const maxBodyH = cardBottomLimit - cardTop - (pad * 2) - headerH - bodyGap;
  const fit = maxBodyH > 0 ? fitPoints(newsPoints(newsData), textW, maxBodyH) : null;

  if (fit) {
    const cardH = (pad * 2) + headerH + bodyGap + fit.height;

    // Card (same style as the calendar container)
    const cardPath = new Path();
    cardPath.addRoundedRect(new Rect(cardX, cardTop, cardW, cardH), CONFIG.containerRadius, CONFIG.containerRadius);
    ctx.setFillColor(new Color("#000000", CONFIG.containerOpacity));
    ctx.addPath(cardPath);
    ctx.fillPath();

    // Header
    const headerRect = new Rect(cardX + pad, cardTop + pad, textW, headerH);
    ctx.setFont(Font.boldSystemFont(headerSize));
    ctx.setTextColor(isError ? CONFIG.colors.today : CONFIG.colors.text);
    ctx.setTextAlignedLeft();
    ctx.drawTextInRect(headerLeft, headerRect);
    if (headerRight) {
      ctx.setTextColor(isStale ? CONFIG.colors.text : CONFIG.colors.stats);
      ctx.setTextAlignedRight();
      ctx.drawTextInRect(headerRight, headerRect);
    }

    // Points: "•" (or ⚠️ for actively exploited) in the bullet column, text
    // indented after it. Rects get a little slack so a line never wraps/clips.
    const textColor = isStale ? new Color(CONFIG.newsTextColor.hex, 0.55) : CONFIG.newsTextColor;
    const font = Font.systemFont(fit.size);
    ctx.setTextAlignedLeft();
    let y = cardTop + pad + headerH + bodyGap;
    for (const item of fit.items) {
      ctx.setFont(item.warn ? font : Font.boldSystemFont(fit.size));
      ctx.setTextColor(item.warn ? textColor : CONFIG.colors.stats);
      ctx.drawTextInRect(item.warn ? "⚠️" : "•", new Rect(cardX + pad, y, fit.indent + fit.size, fit.lineH));
      ctx.setFont(font);
      ctx.setTextColor(textColor);
      for (const line of item.lines) {
        ctx.drawTextInRect(line, new Rect(cardX + pad + fit.indent, y, textW - fit.indent + pad * 0.8, fit.lineH));
        y += fit.lineH;
      }
      y += fit.gap;
    }
  }
}

// --- OUTPUT ---
const image = ctx.getImage();
const fm = FileManager.local();
const path = fm.joinPath(fm.temporaryDirectory(), "wallpaper_auto.png");
fm.writeImage(path, image);

Script.setShortcutOutput(path);
Script.complete();