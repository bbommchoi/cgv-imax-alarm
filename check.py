# -*- coding: utf-8 -*-
"""
CGV 광교 · 오디세이 · IMAX 예매 오픈 알림 봇 (완성판)
=====================================================
1) CGV 창구에 "광교에서 오디세이 예매 가능한 날짜" 를 물어본다
2) 가능하면 회차(시간)까지 물어본다
3) 지난번(state.json)과 비교해서 새로 열린 게 있으면 Teams 로 알린다
"""
import json, os, re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib import request, error
from urllib.parse import urlencode

# ---------------- 설정 (GitHub Variables 로 바꿀 수 있음)
CO = os.environ.get("CO_CD", "A420")
SITE = os.environ.get("SITE_NO", "0257")          # 광교
SITE_NM = os.environ.get("THEATER_NAME", "CGV 광교")
MOVIE = os.environ.get("MOVIE_KEYWORD", "오디세이")
MOV_FALLBACK = os.environ.get("MOV_NO", "30001323")
SCREEN = os.environ.get("SCREEN_KEYWORD", "IMAX")
IMAX_ATTR = os.environ.get("IMAX_ATTR_CD", "04")
WEBHOOK = os.environ.get("TEAMS_WEBHOOK_URL", "").strip()
BOOK_URL = "https://cgv.co.kr/cnm/movieBook/movie"
# 이 날짜(KST, YYYYMMDD)까지는 변화가 없어도 "이상 없음" 을 알려준다. 지나면 자동으로 조용해짐.
HEARTBEAT_UNTIL = os.environ.get("HEARTBEAT_UNTIL", "20000101")   # 과거 날짜 = 확인 알림 끔
RANGE_DAYS = int(os.environ.get("RANGE_DAYS", "40"))    # 오늘부터 며칠 앞까지 직접 확인할지
EMPTY_STOP = int(os.environ.get("EMPTY_STOP", "10"))    # 빈 날이 이만큼 연속되면 그만

API = "https://cgv.co.kr/api/v1/booking/"
KST = timezone(timedelta(hours=9))
STATE = Path("state.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")


def log(m):
    print(f"[{datetime.now(KST):%H:%M:%S}] {m}", flush=True)


def api(name, params, timeout=15):
    url = API + name + "?" + urlencode(params, encoding="utf-8")
    req = request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9", "Referer": BOOK_URL})
    try:
        with request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", "replace"))
        except Exception:
            return e.code, None
    except Exception as e:
        log(f"  통신 오류 {name}: {type(e).__name__}")
        return 0, None


# ---------------- 1) 영화번호 찾기
def find_mov_no():
    st, js = api("searchAtktTopPostrList", {"coCd": CO, "movNm": "", "div": "", "attrCd": ""})
    if st == 200 and js:
        for rec in js.get("data") or []:
            if isinstance(rec, dict) and MOVIE in str(rec.get("movNm", "")):
                no = str(rec.get("movNo") or "")
                if no:
                    log(f"영화 '{rec.get('movNm')}' → movNo={no}")
                    return no
    log(f"영화번호를 목록에서 못 찾아 기본값 사용: {MOV_FALLBACK}")
    return MOV_FALLBACK


# ---------------- 2) 예매 가능 날짜 (참고용 — 이 목록은 늦게 갱신될 수 있어 믿지 않는다)
def peek_date_list(mov_no):
    out = {}
    for tag, extra in (("IMAX필터", {"div": "CUST_EXPO_MOVTYP_CD", "attrCd": IMAX_ATTR}),
                       ("필터없음", {})):
        params = {"coCd": CO, "movNo": mov_no, "siteNo": SITE}
        params.update(extra)
        st, js = api("searchSiteScnscYmdListByMov", params)
        got = []
        if st == 200 and js:
            got = sorted({str((r or {}).get("scnYmd") or "") for r in (js.get("data") or [])} - {""})
        out[tag] = got
        log(f"  [참고] 날짜목록({tag}) {len(got)}일" + (f" {got[0]}~{got[-1]}" if got else ""))
    return out


# ---------------- 3) 회차(시간) — 파라미터 자동 탐색
SCOPES = ["01", "02", "03", "04", "05", "00", "1", "2", "3", "10", "20"]


def times_for(mov_no, ymd, scope_cache):
    scopes = [scope_cache[0]] if scope_cache[0] else SCOPES
    for scope in scopes:
        st, js = api("searchSchByMov", {"coCd": CO, "movNo": mov_no, "siteNo": SITE,
                                        "scnYmd": ymd, "rtctlScopCd": scope})
        if st != 200 or not js or not js.get("data"):
            continue
        if not scope_cache[0]:
            scope_cache[0] = scope
            log(f"★ 시간표 창구 열림! rtctlScopCd={scope}")
            log(f"  응답 견본: {json.dumps(js['data'], ensure_ascii=False)[:900]}")
        return extract_times(js["data"])
    return []


TIME_RE = re.compile(r"^([01]\d|2[0-3])[:]?([0-5]\d)$")
IMAX_GRAD_CD = os.environ.get("IMAX_GRAD_CD", "03")   # tcscnsGradCd 03 = 아이맥스
NAME_KEYS = ("scnsNm", "expoScnsNm", "tcscnsGradNm", "sascnsGradNm", "movkndDsplNm")
START_KEYS = ("scnsrtTm", "scnStrtTm", "playStrtTm", "strtTm", "scnStartTime", "playStrtTime")

_seen_halls = {}


def _hhmm(v):
    if not isinstance(v, str):
        return None
    m = TIME_RE.match(v.strip())
    return f"{m.group(1)}:{m.group(2)}" if m else None


def is_imax_record(rec):
    if str(rec.get("tcscnsGradCd", "")) == IMAX_GRAD_CD:
        return True
    blob = " ".join(str(rec.get(k, "") or "") for k in NAME_KEYS)
    return (SCREEN.upper() in blob.upper()) or ("아이맥스" in blob)


def extract_times(data):
    """상영 회차 레코드 중 IMAX 관만 골라 시작 시각을 뽑는다."""
    found = set()

    def visit(o, inherited=False, label=""):
        if isinstance(o, dict):
            mine = is_imax_record(o)
            st = next((_hhmm(o.get(k)) for k in START_KEYS if _hhmm(o.get(k))), None)
            if st:
                hall = str(o.get("scnsNm") or o.get("expoScnsNm") or label or "?")
                grad = str(o.get("tcscnsGradNm") or o.get("tcscnsGradCd") or "?")
                ok = mine or inherited
                _seen_halls[f"{hall} / {grad}"] = ("IMAX 포함 ✅" if ok else "제외")
                if ok:
                    found.add(st)
                return
            lab = str(o.get("scnsNm") or o.get("expoScnsNm") or label or "")
            for v in o.values():
                visit(v, inherited or mine, lab)
        elif isinstance(o, list):
            for v in o:
                visit(v, inherited, label)

    visit(data)
    return sorted(found)


# ---------------- 기억
STATE_VER = 2   # 판정 규칙이 바뀌면 올린다 -> 옛 기록 무효화


def load():
    if STATE.exists():
        try:
            d = json.loads(STATE.read_text(encoding="utf-8"))
            if int(d.get("v", 0)) != STATE_VER:
                log("판정 규칙이 바뀌어 기준을 새로 잡습니다 (이번엔 알림 없음)")
                return set()
            return set(d.get("slots", []))
        except Exception:
            pass
    return set()


def save(slots):
    STATE.write_text(json.dumps(
        {"v": STATE_VER, "updated": datetime.now(KST).isoformat(),
         "count": len(slots), "slots": sorted(slots)},
        ensure_ascii=False, indent=2), encoding="utf-8")


def pretty(ymd):
    return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}" if re.fullmatch(r"20\d{6}", ymd) else ymd


# ---------------- 알림
def notify(new, total, mode):
    if not WEBHOOK:
        log("웹후크가 없어 알림 생략")
        return
    by = {}
    for s in sorted(new):
        d, _, t = s.partition(" ")
        by.setdefault(pretty(d), []).append(t)
    lines = [f"**{d}**" + (f"  {'  '.join(t for t in ts if t)}" if any(ts) else "  (날짜 오픈)")
             for d, ts in sorted(by.items())]
    text = "\n\n".join(lines[:20])

    card = {"type": "message", "attachments": [{
        "contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None,
        "content": {"type": "AdaptiveCard",
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "version": "1.4",
                    "body": [
                        {"type": "TextBlock", "size": "Medium", "weight": "Bolder", "wrap": True,
                         "text": f"🎬 {SITE_NM} {SCREEN} · 「{MOVIE}」 예매 새로 열렸어요!"},
                        {"type": "TextBlock", "wrap": True, "spacing": "Small",
                         "text": f"새로 열린 것 **{len(new)}건** · 현재 전체 {total}건 ({mode})"},
                        {"type": "TextBlock", "wrap": True, "text": text},
                        {"type": "TextBlock", "isSubtle": True, "size": "Small", "wrap": True,
                         "text": f"확인 {datetime.now(KST):%m/%d %H:%M} KST"}],
                    "actions": [{"type": "Action.OpenUrl", "title": "CGV에서 예매하기", "url": BOOK_URL}],
                    "msteams": {"width": "Full"}}}]}
    body = json.dumps(card, ensure_ascii=False).encode("utf-8")
    req = request.Request(WEBHOOK, data=body,
                          headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with request.urlopen(req, timeout=30) as r:
            resp = r.read().decode("utf-8", "replace")[:300]
            log(f"✅ Teams 알림 전송 (응답 {r.status}) {resp}")
    except error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        log(f"❌ Teams 알림 실패 (HTTP {e.code}) {detail}")
    except Exception as e:
        log(f"❌ Teams 알림 실패: {type(e).__name__} {e}")


def heartbeat(total, mode, dates):
    """변화가 없을 때 보내는 '이상 없음' 알림 (HEARTBEAT_UNTIL 까지만)."""
    today = datetime.now(KST).strftime("%Y%m%d")
    if today > HEARTBEAT_UNTIL:
        return
    if not WEBHOOK:
        log("웹후크가 없어 이상없음 알림 생략")
        return
    span = f"{pretty(dates[0])} ~ {pretty(dates[-1])}" if dates else "-"
    card = {"type": "message", "attachments": [{
        "contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None,
        "content": {"type": "AdaptiveCard",
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "version": "1.4",
                    "body": [
                        {"type": "TextBlock", "wrap": True, "weight": "Bolder",
                         "text": f"✅ 확인 완료 · 새로 열린 회차 없음"},
                        {"type": "FactSet", "facts": [
                            {"title": "대상", "value": f"{SITE_NM} {SCREEN} · 「{MOVIE}」"},
                            {"title": "현재", "value": f"{total}건 ({mode})"},
                            {"title": "예매 가능", "value": span},
                            {"title": "확인 시각", "value": f"{datetime.now(KST):%m/%d %H:%M} KST"}]},
                        {"type": "TextBlock", "isSubtle": True, "size": "Small", "wrap": True,
                         "text": f"이 확인 알림은 {pretty(HEARTBEAT_UNTIL)} 까지만 옵니다."}],
                    "msteams": {"width": "Full"}}}]}
    body = json.dumps(card, ensure_ascii=False).encode("utf-8")
    req = request.Request(WEBHOOK, data=body,
                          headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with request.urlopen(req, timeout=30) as r:
            log(f"🟢 이상없음 알림 전송 (응답 {r.status})")
    except Exception as e:
        log(f"이상없음 알림 실패: {type(e).__name__}")


def collect_slots(mov):
    """오늘부터 하루씩 직접 물어보며 IMAX 회차를 모은다 (날짜 목록에 의존하지 않음)."""
    today = datetime.now(KST).date()
    scope = [None]
    slots = set()
    empty = 0
    last_hit = None
    asked = 0

    for i in range(RANGE_DAYS):
        ymd = (today + timedelta(days=i)).strftime("%Y%m%d")
        times = times_for(mov, ymd, scope)
        asked += 1
        if times:
            empty = 0
            last_hit = ymd
            for t in times:
                slots.add(f"{ymd} {t}")
            log(f"   {pretty(ymd)} → IMAX {len(times)}회차 {times}")
        else:
            empty += 1
            if slots and empty >= EMPTY_STOP:
                log(f"   {pretty(ymd)} 이후 {EMPTY_STOP}일 연속 없음 → 여기서 중단")
                break
        if scope[0] is None and i >= 4:
            log("   ⚠️ 시간표 창구가 계속 안 열려요 (rtctlScopCd 미확정)")
            break

    log(f"   조회한 날짜 {asked}일 · 마지막 상영일 {pretty(last_hit) if last_hit else '-'}")
    return slots, scope[0]


# ---------------- main
def main():
    log(f"감시: {SITE_NM}({SITE}) / {MOVIE} / {SCREEN}")
    mov = find_mov_no()
    peek_date_list(mov)          # 참고용 (문제 추적에 도움)

    slots, scope = collect_slots(mov)
    if not slots:
        log("❌ 회차를 하나도 못 받았어요. 이번은 건너뜁니다 (기록은 그대로 둠).")
        return

    mode = "회차 기준"
    log(f"이번 확인: {len(slots)}건 · 상영관 판정: " +
        ", ".join(f"{v} {k}" for k, v in sorted(_seen_halls.items())))

    known = load()
    new = slots - known
    gone = known - slots

    if not known:
        log("첫 실행 → 지금 상태를 기준으로 저장만 (알림 없음)")
        save(slots)
        heartbeat(len(slots), mode, sorted({s.split()[0] for s in slots}))
        return

    if new:
        log(f"🎉 새로 열린 것 {len(new)}건")
        for x in sorted(new):
            log(f"   + {x}")
        notify(new, len(slots), mode)
    else:
        log(f"변화 없음 (지나간 회차 {len(gone)}건 정리)")
        heartbeat(len(slots), mode, sorted({s.split()[0] for s in slots}))

    if slots != known:
        save(slots)


if __name__ == "__main__":
    main()
