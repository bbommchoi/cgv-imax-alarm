# -*- coding: utf-8 -*-
"""유력 창구들의 응답 내용을 그대로 펼쳐본다 (마지막 정찰)."""
import json
from datetime import datetime, timezone, timedelta
from urllib import request, error
from urllib.parse import urlencode

BASE = "https://cgv.co.kr/api/v1/booking/"
CO, MOV, SITE, IMAX = "A420", "30001323", "0257", "04"
KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).strftime("%Y%m%d")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")


def get(name, params):
    url = BASE + name + "?" + urlencode(params, encoding="utf-8")
    req = request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://cgv.co.kr/cnm/movieBook/movie"})
    try:
        with request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except error.HTTPError as e:
        try: return e.code, e.read().decode("utf-8", "replace")
        except Exception: return e.code, ""
    except Exception as e:
        return 0, f"{type(e).__name__}"


P_MOVSITE = {"coCd": CO, "movNo": MOV, "siteNo": SITE}
P_SITE = {"coCd": CO, "siteNo": SITE}
P_IMAX = {"coCd": CO, "movNo": MOV, "siteNo": SITE, "div": "CUST_EXPO_MOVTYP_CD", "attrCd": IMAX}
P_YMD = {"coCd": CO, "movNo": MOV, "siteNo": SITE, "scnYmd": TODAY}

TARGETS = [
    ("searchSiteScnscYmdListByMov", P_MOVSITE, 4000),
    ("searchSiteScnscYmdListBySite", P_SITE, 4000),
    ("searchSscnsSchdExistList", P_MOVSITE, 4000),
    ("searchLastScnDay", P_MOVSITE, 2000),
    ("searchSscnsCdList", P_MOVSITE, 3000),
    ("searchSscnsSchdCntList", P_MOVSITE, 4000),
    ("searchScnsMngList", P_MOVSITE, 2000),
    ("searchSchByMov", P_YMD, 3000),
    ("searchMovScnInfo", P_YMD, 3000),
    ("searchSiteScnscYmdListByMov", P_IMAX, 2000),
]

print(f"오늘={TODAY}  영화={MOV}(오디세이)  극장={SITE}(광교)  IMAX={IMAX}")

for name, p, limit in TARGETS:
    st, raw = get(name, p)
    print("\n" + "=" * 74)
    print(f"■ {name}")
    print(f"  파라미터: {p}")
    print(f"  status={st} 길이={len(raw)}")
    if st != 200:
        print("  본문:", raw[:400]); continue
    try:
        pretty = json.dumps(json.loads(raw), ensure_ascii=False, indent=1)
    except Exception:
        pretty = raw
    print(pretty[:limit])
    if len(pretty) > limit:
        print(f"  ...(뒤에 {len(pretty)-limit}자 더 있음)")

print("\n" + "=" * 74)
print("끝.")
