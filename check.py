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


# ---------------- 2) 예매 가능 날짜
def get_dates(mov_no):
    st, js = api("searchSiteScnscYmdListByMov",
                 {"coCd": CO, "movNo": mov_no, "siteNo": SITE,
                  "div": "CUST_EXPO_MOVTYP_CD", "attrCd": IMAX_ATTR})
    if st != 200 or not js:
        log(f"날짜 조회 실패 (status={st})")
        return []
    out = []
    for rec in js.get("data") or []:
        y = str((rec or {}).get("scnYmd") or "")
        if re.fullmatch(r"20\d{6}", y):
            out.append(y)
    return sorted(set(out))


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
    with request.urlopen(req, timeout=30) as r:
        log(f"✅ Teams 알림 전송 (응답 {r.status})")


# ---------------- main
def main():
    log(f"감시: {SITE_NM}({SITE}) / {MOVIE} / {SCREEN}")
    mov = find_mov_no()
    dates = get_dates(mov)
    if not dates:
        log("❌ 예매 가능 날짜를 못 받았어요. 이번 회차는 건너뜁니다.")
        return
    log(f"예매 가능 날짜 {len(dates)}일: {dates[0]} ~ {dates[-1]}")

    scope = [None]
    slots, mode = set(), "날짜 기준"
    for ymd in dates:
        ts = times_for(mov, ymd, scope)
        if ts:
            mode = "회차 기준"
            for t in ts:
                slots.add(f"{ymd} {t}")
        else:
            slots.add(f"{ymd} ")
    if scope[0] is None:
        log("시간표 창구는 아직 못 열었어요 → 날짜 단위로 감시합니다 (충분히 동작해요)")
    elif _seen_halls:
        log("상영관 판정 결과:")
        for hall, verdict in sorted(_seen_halls.items()):
            log(f"   {verdict}  {hall}")
    log(f"이번 확인: {len(slots)}건 ({mode})")

    known = load()
    new = slots - known
    if not known:
        log("첫 실행 → 지금 상태를 기준으로 저장만 (알림 없음)")
        save(slots)
        return
    if new:
        log(f"🎉 새로 열린 것 {len(new)}건: {sorted(new)[:10]}")
        notify(new, len(slots), mode)
    else:
        log("변화 없음")
    save(slots if mode == "회차 기준" else (known | slots))


if __name__ == "__main__":
    main()
