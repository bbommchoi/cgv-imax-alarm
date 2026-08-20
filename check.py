# -*- coding: utf-8 -*-
"""CGV 홈페이지 프로그램 파일을 뒤져서 모든 API 주소를 캐낸다."""
import re, json
from urllib import request, error

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
H = {"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9",
     "Accept": "text/html,application/json,*/*", "Referer": "https://cgv.co.kr/"}


def fetch(url, timeout=25):
    try:
        with request.urlopen(request.Request(url, headers=H), timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return 0, f"{type(e).__name__}"


print("=" * 72)
st, html = fetch("https://cgv.co.kr/cnm/movieBook/movie")
print(f"[페이지] status={st} 길이={len(html)}")

srcs = set(re.findall(r'src="(/_next/static/[^"]+?\.js)"', html))
srcs |= set(re.findall(r'"(/_next/static/chunks/[^"]+?\.js)"', html))
print(f"[스크립트] {len(srcs)}개 발견")

paths = set()
for i, s in enumerate(sorted(srcs)[:60]):
    st2, js = fetch("https://cgv.co.kr" + s)
    if st2 != 200:
        continue
    paths |= set(re.findall(r"[\"'`](/api/v\d/[A-Za-z0-9/_\-]{3,80})", js))
    paths |= set(re.findall(r"[\"'`](/cnm/[a-z]+/search[A-Za-z0-9]{3,60})", js))

print(f"\n[찾은 API 주소] 총 {len(paths)}개")
print("=" * 72)

KEY = ("atkt", "schd", "sched", "scns", "time", "ymd", "play", "book", "site", "screen", "movi")
hot = sorted(p for p in paths if any(k in p.lower() for k in KEY))
cold = sorted(p for p in paths if p not in hot)

print(f"\n★ 예매/시간표 관련해 보이는 것 ({len(hot)}개)")
for p in hot:
    print("   ", p)

print(f"\n(그 외 {len(cold)}개)")
for p in cold[:80]:
    print("   ", p)

# IMAX 속성코드도 확인
print("\n" + "=" * 72)
st3, raw = fetch("https://cgv.co.kr/api/v1/booking/searchAtktTopPostrAttrList?coCd=A420")
print(f"[특별관 코드표] status={st3}")
try:
    for d in json.loads(raw).get("data", []):
        print("   ", json.dumps(d, ensure_ascii=False))
except Exception:
    print("   ", raw[:600])

print("\n" + "=" * 72)
print("끝. 위 내용을 캡처해서 보내주세요.")
