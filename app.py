import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from datetime import date, datetime, timedelta, time
from pathlib import Path
import re
import uuid

st.set_page_config(page_title="SUTD Term 7 Timetable Planner", layout="wide")

DATA_DIR = Path(__file__).parent / "data"

DAY_OFFSET = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4}
DAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri"]
SG_UTC_OFFSET = timedelta(hours=8)  # Singapore is UTC+8, no DST

# Week numbering matches how SUTD communicates it to students: Week 1 is the
# Monday classes start, Week 7 is recess (no lessons), Week 14 is finals.
RECESS_WEEK = 7
FINALS_WEEK = 14
TOTAL_WEEKS = 14

COLORS = [
    "#4C78A8", "#F58518", "#54A24B", "#E45756", "#72B7B2",
    "#EECA3B", "#B279A2", "#FF9DA6", "#9D755D", "#BAB0AC",
    "#8CD17D", "#F2CF5B", "#B6992D", "#E15759", "#79706E",
]


def normalize_code(code):
    """Lossless whitespace/zero-pad cleanup only, e.g. ' 01.107' -> '01.107'
    and '1.107' -> '01.107' (a spreadsheet dropping a leading zero loses no
    information, so this is safe to restore). Deliberately does NOT guess a
    dropped trailing digit (e.g. '1.4' is left as '1.4', not invented into
    '01.400') — matching against exams.csv is strict/exact from here on, so
    a code that was actually mangled just won't match, and shows up as a
    visible warning instead of a silently "fixed" wrong answer."""
    code = str(code).strip()
    m = re.fullmatch(r"(\d{1,2})\.(\d+[A-Za-z]*)", code)
    if not m:
        return code
    whole, rest = m.groups()
    return f"{int(whole):02d}.{rest}"


def normalize_time(s):
    return parse_hhmm(s).strftime("%H:%M")


def normalize_weeks(s):
    return compress_weeks(parse_weeks(s))


@st.cache_data
def load_sessions():
    df = pd.read_csv(DATA_DIR / "sessions.csv", dtype=str)
    df["code"] = df["code"].apply(normalize_code)
    df["start"] = df["start"].apply(normalize_time)
    df["end"] = df["end"].apply(normalize_time)
    df["weeks"] = df["weeks"].apply(normalize_weeks)
    return df


@st.cache_data
def load_exams():
    df = pd.read_csv(DATA_DIR / "exams.csv", dtype=str)
    df["code"] = df["code"].apply(normalize_code)
    return df


def parse_weeks(s):
    weeks = []
    for part in str(s).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-")
            weeks.extend(range(int(a), int(b) + 1))
        else:
            weeks.append(int(part))
    return sorted(set(weeks))


def week_to_monday(week, term_start):
    """week 1 = term_start's week; week numbers otherwise count straight
    through, including the recess week, matching SUTD's own numbering."""
    return term_start + timedelta(days=(week - 1) * 7)


def session_occurrence_dates(row, term_start):
    weeks = parse_weeks(row["weeks"])
    offset = DAY_OFFSET[row["day"]]
    return [week_to_monday(w, term_start) + timedelta(days=offset) for w in weeks]


def compress_weeks(weeks):
    """[1,2,3,5,8,9] -> '1-3, 5, 8-9'"""
    weeks = sorted(set(weeks))
    if not weeks:
        return ""
    ranges = []
    start = prev = weeks[0]
    for w in weeks[1:]:
        if w == prev + 1:
            prev = w
            continue
        ranges.append((start, prev))
        start = prev = w
    ranges.append((start, prev))
    return ", ".join(f"{a}" if a == b else f"{a}-{b}" for a, b in ranges)


def build_term_calendar(term_start):
    rows = []
    for wk in range(1, TOTAL_WEEKS + 1):
        monday = week_to_monday(wk, term_start)
        if wk == RECESS_WEEK:
            status = "Recess — no lessons"
        elif wk == FINALS_WEEK:
            status = "Finals"
        else:
            status = "Teaching"
        rows.append({"Week": wk, "Commences": monday.strftime("%a, %d %b %Y"), "Status": status})
    return pd.DataFrame(rows)


def parse_hhmm(s):
    h, m = str(s).split(":")
    return time(int(h), int(m))


def _minutes(t):
    return t.hour * 60 + t.minute


def _layout_day_columns(events):
    """Google-Calendar-style overlap layout: each event gets a column index
    and the total column count of its overlap cluster, so overlapping
    events sit side by side instead of stacking on top of each other."""
    n = len(events)
    columns = [-1] * n
    col_end = []
    for i, ev in enumerate(events):
        s = _minutes(ev["start_t"])
        placed = False
        for c, end_t in enumerate(col_end):
            if end_t <= s:
                columns[i] = c
                col_end[c] = _minutes(ev["end_t"])
                placed = True
                break
        if not placed:
            columns[i] = len(col_end)
            col_end.append(_minutes(ev["end_t"]))

    group_id = [-1] * n
    gid = 0
    for i in range(n):
        if group_id[i] != -1:
            continue
        stack = [i]
        group_id[i] = gid
        while stack:
            cur = stack.pop()
            cs, ce = _minutes(events[cur]["start_t"]), _minutes(events[cur]["end_t"])
            for j in range(n):
                if group_id[j] == -1:
                    js, je = _minutes(events[j]["start_t"]), _minutes(events[j]["end_t"])
                    if cs < je and js < ce:
                        group_id[j] = gid
                        stack.append(j)
        gid += 1

    group_cols = {}
    for i in range(n):
        group_cols[group_id[i]] = max(group_cols.get(group_id[i], 0), columns[i] + 1)

    return [(columns[i], group_cols[group_id[i]]) for i in range(n)]


def build_calendar_html(edited_df, color_map):
    px_per_hour = 60
    all_starts = [parse_hhmm(s) for s in edited_df["start"]]
    all_ends = [parse_hhmm(s) for s in edited_df["end"]]
    min_hour = min([8] + [t.hour for t in all_starts])
    max_hour = max([18] + [t.hour + (1 if t.minute else 0) for t in all_ends])
    total_height = (max_hour - min_hour) * px_per_hour

    day_cols_html = []
    for day in DAY_ORDER:
        day_df = edited_df[edited_df["day"] == day].copy()
        events = day_df.to_dict("records")
        for ev in events:
            ev["start_t"] = parse_hhmm(ev["start"])
            ev["end_t"] = parse_hhmm(ev["end"])
        events.sort(key=lambda e: _minutes(e["start_t"]))
        layout = _layout_day_columns(events) if events else []

        blocks = []
        for ev, (col, total_cols) in zip(events, layout):
            top = _minutes(ev["start_t"]) - min_hour * 60
            height = max(_minutes(ev["end_t"]) - _minutes(ev["start_t"]), 24)
            width_pct = 100 / total_cols
            left_pct = col * width_pct
            color = color_map[ev["code"]]
            week_label = compress_weeks(parse_weeks(ev["weeks"]))
            blocks.append(
                f'<div class="event" style="top:{top}px;height:{height}px;'
                f'left:calc({left_pct}% + 2px);width:calc({width_pct}% - 4px);'
                f'background:{color}26;border-left:3px solid {color};">'
                f'<div class="ev-time">{ev["start"]}–{ev["end"]}</div>'
                f'<div class="ev-code">{ev["code"]}</div>'
                f'<div class="ev-venue">{ev["venue"]}</div>'
                f'<div class="ev-weeks">Wk {week_label}</div>'
                f"</div>"
            )

        lines = "".join(
            f'<div class="hour-line" style="top:{(h - min_hour) * px_per_hour}px;"></div>'
            for h in range(min_hour, max_hour + 1)
        )
        day_cols_html.append(f'<div class="day-col">{lines}{"".join(blocks)}</div>')

    hour_labels = "".join(
        f'<div class="hour-row" style="top:{(h - min_hour) * px_per_hour}px;">{h:02d}:00</div>'
        for h in range(min_hour, max_hour + 1)
    )
    day_headers = "".join(f'<div class="day-header">{d}</div>' for d in DAY_ORDER)

    html = f"""
    <style>
      * {{ box-sizing: border-box; font-family: -apple-system, "Segoe UI", Roboto, sans-serif; }}
      body {{ margin:0; background:#fff; }}
      .header-row {{ display:flex; }}
      .header-spacer {{ width:52px; flex-shrink:0; }}
      .day-header {{ flex:1; text-align:center; font-weight:600; padding:8px 0;
        border-bottom:2px solid #ddd; font-size:13px; color:#222; }}
      .cal-wrap {{ display:flex; border:1px solid #ddd; border-radius:8px; overflow:hidden; }}
      .time-col {{ width:52px; flex-shrink:0; position:relative; background:#fafafa;
        border-right:1px solid #eee; }}
      .hour-row {{ position:absolute; right:6px; transform:translateY(-50%);
        font-size:11px; color:#888; }}
      .grid-body {{ display:flex; flex:1; position:relative; }}
      .day-col {{ flex:1; position:relative; border-right:1px solid #f0f0f0; }}
      .day-col:last-child {{ border-right:none; }}
      .hour-line {{ position:absolute; left:0; right:0; border-top:1px solid #f0f0f0; }}
      .event {{ position:absolute; border-radius:4px; padding:3px 5px; overflow:hidden;
        font-size:11px; color:#222; box-shadow:0 1px 2px rgba(0,0,0,0.08); }}
      .ev-time {{ font-weight:700; font-size:10.5px; }}
      .ev-code {{ font-weight:700; }}
      .ev-venue {{ color:#555; font-size:10px; }}
      .ev-weeks {{ color:#888; font-size:9px; }}
    </style>
    <div class="header-row"><div class="header-spacer"></div>{day_headers}</div>
    <div class="cal-wrap" style="height:{total_height}px;">
      <div class="time-col">{hour_labels}</div>
      <div class="grid-body">{"".join(day_cols_html)}</div>
    </div>
    """
    return html, total_height + 60


def fold_ics_line(line):
    # RFC5545 line folding at 75 octets
    out = []
    while len(line.encode("utf-8")) > 75:
        # find a safe split point (75 chars is a good approx for ascii-heavy text)
        cut = 75
        out.append(line[:cut])
        line = " " + line[cut:]
    out.append(line)
    return "\r\n".join(out)


def build_ics(events, calendar_name="SUTD Term 7 Timetable"):
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Timetable Planner//EN",
        "CALSCALE:GREGORIAN",
        f"X-WR-CALNAME:{calendar_name}",
    ]
    now_stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    for ev in events:
        dtstart_utc = (datetime.combine(ev["date"], ev["start"]) - SG_UTC_OFFSET).strftime("%Y%m%dT%H%M%SZ")
        dtend_utc = (datetime.combine(ev["date"], ev["end"]) - SG_UTC_OFFSET).strftime("%Y%m%dT%H%M%SZ")
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{uuid.uuid4()}@timetable-planner")
        lines.append(f"DTSTAMP:{now_stamp}")
        lines.append(f"DTSTART:{dtstart_utc}")
        lines.append(f"DTEND:{dtend_utc}")
        lines.append(fold_ics_line(f"SUMMARY:{ev['summary']}"))
        lines.append(fold_ics_line(f"LOCATION:{ev.get('location', '')}"))
        if ev.get("description"):
            desc = ev["description"].replace("\n", "\\n")
            lines.append(fold_ics_line(f"DESCRIPTION:{desc}"))
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def main():
    st.title("SUTD Term 7 Timetable Planner")
    st.caption(
        "Pick your modules, check for clashes, and export a .ics file you can import "
        "into Google/Outlook/Apple Calendar."
    )

    sessions = load_sessions()
    exams = load_exams()

    with st.sidebar:
        st.header("Term settings")
        term_start = st.date_input("Week 1 starts (Monday)", value=date(2026, 9, 14))
        st.caption(
            f"Week {RECESS_WEEK} is recess (no lessons) and Week {FINALS_WEEK} is finals week, "
            "matching the official SUTD Term 7 calendar. Adjust the start date only if the "
            "calendar changes."
        )
        include_exams = st.checkbox("Include final exams in export", value=True)

        st.divider()
        st.header("Data quality")
        st.caption(
            "Session times were extracted from grid-style PDF timetables. Rows flagged "
            "'low' or 'medium' confidence should be double-checked against the original "
            "PDF before you rely on them. Edit any session below the calendar if needed."
        )

    with st.expander(f"Term calendar (Week 1 – Week {TOTAL_WEEKS})", expanded=False):
        calendar_df = build_term_calendar(term_start)

        def highlight_status(row):
            if row["Status"] == "Recess — no lessons":
                return ["background-color: #4a3b1a"] * len(row)
            if row["Status"] == "Finals":
                return ["background-color: #3a1a1a"] * len(row)
            return [""] * len(row)

        st.dataframe(
            calendar_df.style.apply(highlight_status, axis=1),
            use_container_width=True,
            hide_index=True,
        )

    # One catalog entry per module `code`, no matter what each individual
    # session row's `name` text says. Deduplicating on the (code, name) pair
    # instead would silently split a module into multiple, inconsistent
    # dropdown entries if any one row's name text differs even slightly
    # (e.g. one row says "(CS01)" and another doesn't) — code is the only
    # strict, reliable identity for a module.
    catalog = (
        sessions.groupby("code", sort=False)["name"]
        .first()
        .reset_index()
        .sort_values("code")
        .assign(label=lambda d: d["code"] + " — " + d["name"])
    )

    st.subheader("1. Select your modules")
    selected_labels = st.multiselect(
        "Modules",
        options=catalog["label"].tolist(),
        help="Includes ESD core/elective modules and HASS/TE elective options.",
    )
    selected_codes = catalog[catalog["label"].isin(selected_labels)]["code"].tolist()

    if not selected_codes:
        st.info("Select at least one module above to build your timetable.")
        return

    color_map = {code: COLORS[i % len(COLORS)] for i, code in enumerate(selected_codes)}

    sel_sessions = sessions[sessions["code"].isin(selected_codes)].copy()

    st.subheader("2. Review / correct session details")
    st.caption(
        "`weeks` uses the Week numbers from the term calendar above (e.g. `1-6,8-13` = "
        "every teaching week except recess)."
    )
    edited = st.data_editor(
        sel_sessions,
        num_rows="fixed",
        use_container_width=True,
        column_config={
            "confidence": st.column_config.SelectboxColumn(options=["high", "medium", "low"]),
        },
        key="session_editor",
    )

    # --- Conflict detection (accounting for week overlap, not just day/time) ---
    st.subheader("3. Clash check")
    conflicts = []
    rows = edited.to_dict("records")
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            a, b = rows[i], rows[j]
            if a["code"] == b["code"] or a["day"] != b["day"]:
                continue
            a_start, a_end = parse_hhmm(a["start"]), parse_hhmm(a["end"])
            b_start, b_end = parse_hhmm(b["start"]), parse_hhmm(b["end"])
            if not overlaps(a_start, a_end, b_start, b_end):
                continue
            a_weeks, b_weeks = set(parse_weeks(a["weeks"])), set(parse_weeks(b["weeks"]))
            if a_weeks & b_weeks:
                conflicts.append((a, b, sorted(a_weeks & b_weeks)))

    if conflicts:
        for a, b, weeks in conflicts:
            week_label = f"weeks {compress_weeks(weeks)}" if len(weeks) > 1 else f"week {weeks[0]}"
            st.warning(
                f"Clash on {a['day']}: **{a['code']}** ({a['start']}-{a['end']}) overlaps "
                f"**{b['code']}** ({b['start']}-{b['end']}) in {week_label}"
            )
    else:
        st.success("No clashes among your selected modules.")

    # --- Weekly grid view (Google Calendar style) ---
    st.subheader("4. Weekly view")
    st.caption(
        "A typical week across the whole term — overlapping sessions sit side by side. "
        "Modules that run in different weeks (e.g. an alternating elective slot) may "
        "appear here without actually clashing; check section 3 above for real clashes."
    )
    cal_html, cal_height = build_calendar_html(edited, color_map)
    components.html(cal_html, height=cal_height, scrolling=False)

    # --- Exams ---
    st.subheader("5. Final exams for selected modules")
    st.caption(f"Finals take place in Week {FINALS_WEEK}, starting {week_to_monday(FINALS_WEEK, term_start).strftime('%d %b %Y')}.")
    matched_exams = exams[exams["code"].isin(selected_codes)].copy()
    has_exam = matched_exams[matched_exams["date"].notna() & (matched_exams["date"] != "")]
    no_exam = matched_exams[matched_exams["date"].isna() | (matched_exams["date"] == "")]

    unmatched_codes = sorted(set(selected_codes) - set(exams["code"]))
    if unmatched_codes:
        st.warning(
            "No exam record at all for: " + ", ".join(unmatched_codes) + ". "
            "This code doesn't appear in data/exams.csv — check for a typo or "
            "formatting mismatch (strict matching, no auto-correction) rather "
            "than assuming there's simply no final exam."
        )

    if not has_exam.empty:
        st.dataframe(
            has_exam[["code", "name", "date", "start", "end", "remarks"]],
            use_container_width=True,
            hide_index=True,
        )
    if not no_exam.empty:
        st.caption(
            "No final exam scheduled for: " + ", ".join(no_exam["code"].tolist())
        )

    # --- ICS export ---
    st.subheader("6. Export")
    events = []
    for _, r in edited.iterrows():
        for d in session_occurrence_dates(r, term_start):
            events.append(
                {
                    "date": d,
                    "start": parse_hhmm(r["start"]),
                    "end": parse_hhmm(r["end"]),
                    "summary": f"{r['code']} {r['session_type']}",
                    "location": r["venue"],
                    "description": f"{r['name']}\nFaculty: {r['faculty']}",
                }
            )

    if include_exams and not has_exam.empty:
        for _, r in has_exam.iterrows():
            exam_date = datetime.strptime(r["date"], "%Y-%m-%d").date()
            events.append(
                {
                    "date": exam_date,
                    "start": parse_hhmm(r["start"]),
                    "end": parse_hhmm(r["end"]),
                    "summary": f"{r['code']} Final Exam",
                    "location": r.get("remarks", ""),
                    "description": r["name"],
                }
            )

    ics_content = build_ics(events)
    st.download_button(
        "Download timetable.ics",
        data=ics_content,
        file_name="timetable.ics",
        mime="text/calendar",
    )
    st.caption(f"{len(events)} calendar events will be generated across the term.")


if __name__ == "__main__":
    main()
