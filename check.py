# -*- coding: utf-8 -*-
"""
CGV 광교 - 오디세이 IMAX 상영 추가 오픈 감시기 (v2)
====================================================
CGV 예매 페이지는 클릭을 해야 정보가 보이기 때문에,
사람이 하는 것과 똑같은 순서로 로봇이 클릭한다.

  1) 예매 페이지 열기
  2) 영화 '오디세이' 고르기
  3) 상영관 필터 'IMAX' 고르기
  4) 극장 '광교' 고르기
  5) 날짜를 하나씩 눌러가며 IMAX관 회차 시간을 모으기
  6) 지난번 목록(state.json)과 비교 → 새로 생긴 게 있으면 Teams 알림
"""

import json
import os
import re
import sys
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib import request as urlrequest

# ------------------------------------------------------------------ 설정
CGV_URL = os.environ.get("CGV_URL", "https://cgv.co.kr/cnm/movieBook/movie").strip()
MOVIE = os.environ.get("MOVIE_KEYWORD", "오디세이").strip()
SCREEN = os.environ.get("SCREEN_KEYWORD", "IMAX").strip()
THEATER = os.environ.get("THEATER_KEYWORD", "광교").strip()
THEATER_NAME = os.environ.get("THEATER_NAME", "CGV 광교").strip()
WEBHOOK = os.environ.get("TEAMS_WEBHOOK_URL", "").strip()
HEADFUL = os.environ.get("HEADFUL", "0") == "1"

STATE_FILE = Path("state.json")
DEBUG_DIR = Path("debug")
KST = timezone(timedelta(hours=9))

TIME_RANGE = re.compile(r"\b([01]?\d|2[0-4]):([0-5]\d)\s*[-~–]\s*([01]?\d|2[0-4]):([0-5]\d)")
TIME_ONE = re.compile(r"\b(([01]?\d|2[0-4]):[0-5]\d)\b")
DAY_CHIP = re.compile(r"^[월화수목금토일]?\s*(\d{1,2})$")


def log(msg):
    print(f"[{datetime.now(KST):%H:%M:%S}] {msg}", flush=True)


# ------------------------------------------------------------------ 기억
def load_state():
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return set(data.get("slots", []))
        except Exception as e:
            log(f"기억 파일 읽기 실패(새로 시작): {e}")
    return set()


def save_state(slots):
    STATE_FILE.write_text(
        json.dumps(
            {"updated": datetime.now(KST).isoformat(), "count": len(slots), "slots": sorted(slots)},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


# ------------------------------------------------------------------ 날짜 계산
def resolve_date(day_num, today=None):
    """화면의 '30' 같은 숫자를 2026-08-30 같은 실제 날짜로 바꾼다."""
    today = today or datetime.now(KST).date()
    y, m = today.year, today.month
    if day_num < today.day - 5:  # 달이 넘어간 경우
        m += 1
        if m > 12:
            m, y = 1, y + 1
    try:
        return date(y, m, day_num).isoformat()
    except ValueError:
        return f"{y}-{m:02d}-{day_num:02d}"


# ------------------------------------------------------------------ 클릭 도우미
def try_click(page, label, *strategies):
    """여러 방법을 차례로 시도해서 하나라도 눌리면 True"""
    for i, loc_fn in enumerate(strategies, 1):
        try:
            loc = loc_fn()
            if loc.count() == 0:
                continue
            loc.first.scroll_into_view_if_needed(timeout=5000)
            loc.first.click(timeout=8000)
            page.wait_for_timeout(2500)
            log(f"  ✔ '{label}' 클릭 성공 (방법 {i})")
            return True
        except Exception as e:
            log(f"  · '{label}' 방법 {i} 실패: {type(e).__name__}")
    log(f"  ✖ '{label}' 을(를) 누르지 못했어요")
    return False


# ------------------------------------------------------------------ IMAX 회차 뽑기
def parse_imax_times(text):
    """화면 글자에서 'IMAX관' 아래에 있는 시작시간들만 뽑는다."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    times = []
    in_imax = False

    for line in lines:
        upper = line.upper()

        # 상영관 제목 줄인지 판단
        is_hall_header = bool(re.search(r"관\s*$", line)) and len(line) <= 30
        if is_hall_header:
            in_imax = SCREEN.upper() in upper
            continue
        if SCREEN.upper() in upper and len(line) <= 40:
            in_imax = True
            continue

        if not in_imax:
            continue

        # 다른 상영관 종류가 나오면 구역 종료
        if any(w in upper for w in ("4DX", "SCREENX", "SCREEN X", "DOLBY", "일반관", "SPHERE")):
            in_imax = False
            continue

        m = TIME_RANGE.search(line)
        if m:
            times.append(f"{int(m.group(1)):02d}:{m.group(2)}")
            continue
        if len(line) <= 14:
            m2 = TIME_ONE.search(line)
            if m2:
                hh, mm = m2.group(1).split(":")
                times.append(f"{int(hh):02d}:{mm}")

    return sorted(set(times))


# ------------------------------------------------------------------ 본체
def collect():
    from playwright.sync_api import sync_playwright

    DEBUG_DIR.mkdir(exist_ok=True)
    slots = set()
    api_hits = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=not HEADFUL, args=["--no-sandbox", "--disable-dev-shm-usage", "--lang=ko-KR"]
        )
        ctx = browser.new_context(
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            viewport={"width": 1600, "height": 1400},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            ),
        )
        page = ctx.new_page()

        # 페이지가 내부적으로 부르는 API를 기록해둔다 (나중에 더 빠른 방식으로 바꿀 때 씀)
        def on_response(resp):
            try:
                if resp.request.resource_type in ("xhr", "fetch"):
                    ct = (resp.headers or {}).get("content-type", "")
                    if "json" in ct:
                        body = resp.text()
                        if MOVIE in body or SCREEN in body or THEATER in body:
                            api_hits.append({"url": resp.url, "sample": body[:1500]})
            except Exception:
                pass

        page.on("response", on_response)

        log(f"1) 페이지 열기: {CGV_URL}")
        page.goto(CGV_URL, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=25000)
        except Exception:
            pass
        page.wait_for_timeout(3500)
        page.screenshot(path=str(DEBUG_DIR / "1_열림.png"), full_page=False)

        log(f"2) 영화 '{MOVIE}' 고르기")
        try_click(
            page,
            MOVIE,
            lambda: page.get_by_role("button", name=re.compile(MOVIE)),
            lambda: page.locator(f"img[alt*='{MOVIE}']"),
            lambda: page.get_by_text(MOVIE, exact=False),
        )
        page.screenshot(path=str(DEBUG_DIR / "2_영화선택.png"))

        log(f"3) 상영관 종류 '{SCREEN}' 고르기")
        try_click(
            page,
            SCREEN,
            lambda: page.get_by_role("button", name=re.compile(rf"^{SCREEN}$", re.I)),
            lambda: page.get_by_text(re.compile(rf"^{SCREEN}$", re.I)),
        )

        log(f"4) 극장 '{THEATER}' 고르기")
        try_click(
            page,
            THEATER,
            lambda: page.get_by_role("button", name=re.compile(rf"^{THEATER}$")),
            lambda: page.get_by_text(re.compile(rf"^{THEATER}$")),
        )
        page.wait_for_timeout(2500)
        page.screenshot(path=str(DEBUG_DIR / "3_극장선택.png"), full_page=True)

        # ---- 날짜 칩 목록 찾기
        log("5) 날짜 목록 찾기")
        chips = []
        candidates = page.locator("button, li, a, div[role='button'], span[role='button']")
        total = min(candidates.count(), 600)
        for i in range(total):
            try:
                el = candidates.nth(i)
                t = (el.inner_text(timeout=1000) or "").strip().replace("\n", " ")
                t = re.sub(r"\s+", " ", t)
                m = DAY_CHIP.match(t)
                if m:
                    day = int(m.group(1))
                    if 1 <= day <= 31:
                        chips.append((day, i))
            except Exception:
                continue

        # 같은 날짜 중복 제거
        seen_days = set()
        uniq = []
        for day, idx in chips:
            if day not in seen_days:
                seen_days.add(day)
                uniq.append((day, idx))

        log(f"   찾은 날짜 칩: {[d for d, _ in uniq]}")

        if not uniq:
            log("   ⚠️ 날짜 칩을 못 찾았어요. 현재 화면만 읽습니다.")
            text = page.inner_text("body")
            (DEBUG_DIR / "page_현재.txt").write_text(text, encoding="utf-8")
            for t in parse_imax_times(text):
                slots.add(f"(날짜미확인) {t}")
        else:
            for day, idx in uniq:
                iso = resolve_date(day)
                try:
                    el = page.locator("button, li, a, div[role='button'], span[role='button']").nth(idx)
                    el.scroll_into_view_if_needed(timeout=5000)
                    el.click(timeout=8000)
                    page.wait_for_timeout(2600)
                except Exception as e:
                    log(f"   {iso} 클릭 실패: {type(e).__name__}")
                    continue

                text = page.inner_text("body")
                (DEBUG_DIR / f"page_{iso}.txt").write_text(text, encoding="utf-8")
                times = parse_imax_times(text)
                log(f"   {iso} → {SCREEN} {len(times)}회차 {times}")
                for t in times:
                    slots.add(f"{iso} {t}")

        page.screenshot(path=str(DEBUG_DIR / "4_마지막.png"), full_page=True)
        browser.close()

    if api_hits:
        (DEBUG_DIR / "api_hits.json").write_text(
            json.dumps(api_hits, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log(f"참고: 관련 API 응답 {len(api_hits)}건을 debug/api_hits.json 에 저장했어요")
        for h in api_hits[:5]:
            log(f"   API → {h['url']}")

    return slots


# ------------------------------------------------------------------ 알림
def send_teams(new_slots, all_slots):
    if not WEBHOOK:
        log("웹후크 주소가 없어 알림을 보내지 않았어요 (테스트 모드)")
        return

    by_date = {}
    for s in sorted(new_slots):
        d, _, t = s.partition(" ")
        by_date.setdefault(d, []).append(t)
    lines = [f"**{d}**  {'  '.join(ts)}" for d, ts in sorted(by_date.items())]
    body_text = "\n\n".join(lines[:15])
    if len(lines) > 15:
        body_text += f"\n\n… 외 {len(lines) - 15}일"

    card = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": {
                    "type": "AdaptiveCard",
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "version": "1.4",
                    "body": [
                        {
                            "type": "TextBlock",
                            "text": f"🎬 {THEATER_NAME} {SCREEN} · 「{MOVIE}」 새 회차 오픈!",
                            "weight": "Bolder",
                            "size": "Medium",
                            "wrap": True,
                        },
                        {
                            "type": "TextBlock",
                            "text": f"새로 열린 회차 **{len(new_slots)}건** · 현재 전체 {len(all_slots)}건",
                            "wrap": True,
                            "spacing": "Small",
                        },
                        {"type": "TextBlock", "text": body_text, "wrap": True},
                        {
                            "type": "TextBlock",
                            "text": f"확인 시각 {datetime.now(KST):%m/%d %H:%M} KST",
                            "isSubtle": True,
                            "size": "Small",
                            "wrap": True,
                        },
                    ],
                    "actions": [
                        {"type": "Action.OpenUrl", "title": "CGV에서 예매하기", "url": CGV_URL}
                    ],
                    "msteams": {"width": "Full"},
                },
            }
        ],
    }

    data = json.dumps(card, ensure_ascii=False).encode("utf-8")
    req = urlrequest.Request(
        WEBHOOK, data=data, headers={"Content-Type": "application/json; charset=utf-8"}
    )
    with urlrequest.urlopen(req, timeout=30) as resp:
        log(f"✅ Teams 알림 전송 완료 (응답 {resp.status})")


# ------------------------------------------------------------------ main
def main():
    log(f"감시 대상: {THEATER_NAME} / {MOVIE} / {SCREEN}")
    try:
        found = collect()
    except Exception:
        log("❌ 페이지를 읽는 중 오류가 났어요:")
        traceback.print_exc()
        sys.exit(1)

    log(f"이번에 찾은 총 회차: {len(found)}건")
    if not found:
        log("⚠️ 회차를 하나도 못 찾았어요. debug 폴더의 화면 캡처와 글자 파일을 확인해주세요.")
        return

    known = load_state()
    new = found - known

    if not known:
        log("첫 실행이라 지금 목록을 기준으로 저장만 하고 알림은 보내지 않아요.")
        save_state(found)
        return

    if new:
        log(f"🎉 새로 생긴 회차 {len(new)}건 → 알림!")
        for s in sorted(new):
            log(f"   + {s}")
        send_teams(new, found)
    else:
        log("변화 없음.")

    save_state(known | found)


if __name__ == "__main__":
    main()
