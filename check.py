# -*- coding: utf-8 -*-
"""CGV API 정찰병 - 광교/오디세이 코드와 시간표 창구를 찾아 출력한다."""
import json, re, os
from datetime import datetime, timezone, timedelta
from urllib import request, error
from urllib.parse import urlencode

BASE = "https://cgv.co.kr/api/v1"
CO = "A420"
MOVIE = os.environ.get("MOVIE_KEYWORD", "오디세이")
THEATER = os.environ.get("THEATER_KEYWORD", "광교")
KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).strftime("%Y%m%d")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"


def get(path, params=None):
    url = BASE + path + ("?" + urlencode(params, encoding="utf-8") if params else "")
    req = request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9", "Referer": "https://cgv.co.kr/cnm/movieBook/movie"})
    try:
        with request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except error.HTTPError as e:
        try: body = e.read().decode("utf-8", "replace")
        except Exception: body = ""
        return e.code, body
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


def find(data, kw):
    out = []
    def rec(o):
        if isinstance(o, dict):
            if kw in json.dumps(o, ensure_ascii=False):
                deeper = [v for v in o.values()
                          if isinstance(v, (dict, list)) and kw in json.dumps(v, ensure_ascii=False)]
                if deeper:
                    for v in deeper: rec(v)
                else:
                    out.append(o)
        elif isinstance(o, list):
            for v in o: rec(v)
    rec(data)
    return out


print("=" * 70)
site_cd = mov_cd = None

for label, path, params, kw in (
    ("극장목록", "/content/site/searchAllRegionAndSite", {"coCd": CO}, THEATER),
    ("영화목록", "/booking/searchAtktTopPostrList", {"coCd": CO, "movNm": "", "div": "", "attrCd": ""}, MOVIE),
):
    st, raw = get(path, params)
    print(f"\n[{label}] status={st} 길이={len(raw)}")
    if st != 200:
        print(f"  본문: {raw[:400]}")
        continue
    try:
        data = json.loads(raw)
    except Exception as e:
        print(f"  JSON 실패 {e}: {raw[:300]}")
        continue
    hits = find(data, kw)
    print(f"  '{kw}' 포함 {len(hits)}건")
    for h in hits[:5]:
        print("   →", json.dumps(h, ensure_ascii=False)[:500])
    if hits:
        for k, v in hits[0].items():
            if isinstance(v, str) and re.search(r"(cd|code)$", k, re.I):
                print(f"   [코드후보] {k} = {v}")
                if label == "극장목록" and site_cd is None: site_cd = v
                if label == "영화목록" and mov_cd is None: mov_cd = v

print("\n" + "=" * 70)
p = {"coCd": CO, "playYmd": TODAY}
if site_cd: p["siteCd"] = site_cd
if mov_cd: p["movCd"] = mov_cd
print(f"[후보탐색] 파라미터 {p}\n")

for c in ["/booking/searchAtktScheduleList", "/booking/searchAtktSchedule",
          "/booking/searchAtktPlayYmdList", "/booking/searchAtktPlayYmd",
          "/booking/searchAtktSiteList", "/booking/searchAtktScnsList",
          "/booking/searchAtktTimeList", "/booking/searchAtktScreenList",
          "/booking/searchAtktScheduleTimeList", "/booking/searchAtktMovieList",
          "/booking/searchAtktTopPostrAttrList", "/content/schedule/searchScheduleList"]:
    st, raw = get(c, p)
    mark = "OK" if st == 200 else ("??" if st in (400, 422, 500) else "XX")
    print(f"  {mark} {c} -> {st} | {raw[:250]}")

print("\n" + "=" * 70)
print("정찰 끝. 위 내용을 캡처해서 보내주세요.")
