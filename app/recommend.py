"""회사 맛집 추천 로직 (노트북 03의 핵심 코드).

흐름: 식당 표 + 직원 리뷰 표 → ① 필수 조건으로 거르기(17강) → ② 보정 점수 계산(13강)
→ ③ 목적에 맞는 정보로 가산점 → ④ 점수 순 정렬 + "왜 추천했나요" 설명.

중요한 약속
- 빈칸은 "모름"이다. 0점이나 "안 됨"으로 바꾸지 않는다(12강).
- 데이터 종류를 표시한다: 실제(카카오·구글), 예시(직접 쓴 직원 리뷰), 가상(시뮬레이션).
"""
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent / "data"
RESTAURANT_FILE = DATA_DIR / "restaurants_with_keywords.csv"
REVIEW_FILE = DATA_DIR / "employee_reviews.csv"
IMPRESSION_FILE = DATA_DIR / "impressions.csv"

REVIEW_COLUMNS = ["review_id", "employee_id", "restaurant_id", "meal_time", "purpose",
                  "party_size", "rating", "comment", "visit_date", "data_type"]

# 식사가 아닌 곳(카페·간식·식품 판매 등)은 추천 대상에서 뺀다. 노트북 02와 같은 기준.
NOT_MEAL = {"간식", "식품판매", "구내식당", "푸드코트"}

PURPOSES = {
    "점심": ["편한 외식", "팀 회식", "외부 관계자 미팅", "혼밥·빠른 식사"],
    "저녁": ["편한 외식", "팀 회식", "외부 관계자 미팅", "축하 자리"],
}

# 보정 점수의 세기. 숫자가 클수록 리뷰가 적은 식당을 평균 쪽으로 더 세게 당긴다.
GOOGLE_PRIOR_COUNT = 20   # 구글 리뷰 20개쯤 쌓여야 그 식당 별점을 절반 정도 믿는다
EMPLOYEE_PRIOR_COUNT = 3  # 직원 리뷰 3개쯤 쌓이면 구글 점수와 반반으로 섞인다
PURPOSE_BONUS = 0.15      # 목적에 맞는 근거 1개당 가산점(별점 단위)


# 소·돼지 구분 단서가 없는 고깃집은 소고기·돼지고기 어느 쪽을 골라도 함께 보여 준다
MEAT_UNKNOWN = "고기(구분 모름)"
MEAT_BOTH = {"소고기", "돼지고기"}
LAST_MENUS = ["기타"]  # 메뉴 목록 맨 끝에 둘 항목


# ---------- 데이터 읽기 ----------
def load_restaurants():
    df = pd.read_csv(RESTAURANT_FILE)
    return df[~df["menu_category"].isin(NOT_MEAL)].reset_index(drop=True)


def menu_options(rest):
    """3단계 메뉴 목록: 식당 수 많은 순, '기타'는 맨 끝, 구분 모름 고깃집은 따로 안 보여 줌."""
    order = rest["menu_category"].value_counts().index.tolist()
    order = [m for m in order if m != MEAT_UNKNOWN and m not in LAST_MENUS]
    return order + [m for m in LAST_MENUS if m in set(rest["menu_category"])]


def expand_menus(menus):
    menus = list(menus or [])
    if MEAT_BOTH & set(menus):
        menus.append(MEAT_UNKNOWN)
    return menus


def load_reviews():
    if REVIEW_FILE.exists():
        return pd.read_csv(REVIEW_FILE)
    return pd.DataFrame(columns=REVIEW_COLUMNS)


def add_review(row):
    """직원 리뷰 1건을 CSV 끝에 덧붙인다."""
    reviews = load_reviews()
    next_no = len(reviews) + 1
    row = {**row, "review_id": f"V{next_no:03d}"}
    reviews = pd.concat([reviews, pd.DataFrame([row])], ignore_index=True)
    reviews[REVIEW_COLUMNS].to_csv(REVIEW_FILE, index=False, encoding="utf-8-sig")
    return row["review_id"]


def log_impressions(result, meal_time, purpose):
    """추천 화면에 보인 식당을 1곳 = 1행으로 기록한다(12강 노출 기록, 나중에 인과분석에 사용)."""
    if result.empty:
        return
    log = pd.DataFrame({
        "shown_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "restaurant_id": result["restaurant_id"].values,
        "rank": range(1, len(result) + 1),
        "meal_time": meal_time,
        "purpose": purpose,
    })
    log.to_csv(IMPRESSION_FILE, mode="a", header=not IMPRESSION_FILE.exists(),
               index=False, encoding="utf-8-sig")


# ---------- ② 점수 ----------
def bayesian_average(mean, count, prior_mean, prior_count):
    """보정평균(13강): (리뷰 수 × 그 식당 평균 + 기준 수 × 전체 평균) ÷ (리뷰 수 + 기준 수)."""
    return (count * mean + prior_count * prior_mean) / (count + prior_count)


def add_scores(rest, reviews, meal_time, purpose, overall):
    """overall = 전체 식당(조건으로 거르기 전)의 구글 별점 평균. 보정평균의 '기준 평균'."""
    rest = rest.copy()

    # 구글 점수: 별점이 없으면 전체 평균(중간값)으로 두고 "정보 없음"이라고 표시한다. 감점하지 않는다.
    has_google = rest["google_rating"].notna()
    rest["google_score"] = overall
    rest.loc[has_google, "google_score"] = bayesian_average(
        rest.loc[has_google, "google_rating"], rest.loc[has_google, "google_rating_count"].fillna(0),
        overall, GOOGLE_PRIOR_COUNT)

    # 직원 점수: 같은 시간·같은 목적으로 다녀온 리뷰를 우선 쓰고, 없으면 그 식당의 전체 직원 리뷰를 쓴다.
    same = reviews[(reviews["meal_time"] == meal_time) & (reviews["purpose"] == purpose)]
    same_stat = same.groupby("restaurant_id")["rating"].agg(["mean", "count"])
    all_stat = reviews.groupby("restaurant_id")["rating"].agg(["mean", "count"])
    stat = same_stat.combine_first(all_stat)
    rest = rest.merge(stat.rename(columns={"mean": "emp_mean", "count": "emp_count"}),
                      left_on="restaurant_id", right_index=True, how="left")
    rest["emp_count"] = rest["emp_count"].fillna(0).astype(int)
    rest["emp_same_purpose"] = rest["restaurant_id"].isin(same_stat.index)

    # 최종 점수: 구글 점수를 출발점으로 두고, 직원 리뷰가 쌓일수록 직원 평균 쪽으로 옮겨 간다.
    rest["score"] = rest["google_score"]
    has_emp = rest["emp_count"] > 0
    rest.loc[has_emp, "score"] = bayesian_average(
        rest.loc[has_emp, "emp_mean"], rest.loc[has_emp, "emp_count"],
        rest.loc[has_emp, "google_score"], EMPLOYEE_PRIOR_COUNT)
    return rest


# ---------- ①, ③ 조건 ----------
def has_keyword(rest, word):
    return rest["review_keywords"].fillna("").str.contains(word, regex=False)


def purpose_evidence(rest, purpose, reviews):
    """목적에 맞는다는 근거를 식당마다 글로 모은다. 근거가 없다고 '안 맞음'은 아니다(모름)."""
    went_for = set(reviews.loc[reviews["purpose"] == purpose, "restaurant_id"])
    level = rest["price_level"].fillna("")
    checks = {
        "편한 외식": [],
        "팀 회식": [
            ("단체 가능(구글)", rest["good_for_groups"] == True),
            ("예약 가능(구글)", rest["reservable"] == True),
            ("리뷰에 '단체·회식'", has_keyword(rest, "단체·회식")),
        ],
        "외부 관계자 미팅": [
            ("예약 가능(구글)", rest["reservable"] == True),
            ("가격대 높음(구글)", level.isin(["비쌈", "아주 비쌈"])),
            ("리뷰에 '접대·미팅'", has_keyword(rest, "접대·미팅")),
            ("리뷰에 '분위기'", has_keyword(rest, "분위기")),
        ],
        "혼밥·빠른 식사": [
            ("걸어서 7분 이내", rest["walk_min"] <= 7),
            ("리뷰에 '빠름'", has_keyword(rest, "빠름")),
            ("리뷰에 '혼밥'", has_keyword(rest, "혼밥")),
        ],
        "축하 자리": [
            ("예약 가능(구글)", rest["reservable"] == True),
            ("리뷰에 '분위기'", has_keyword(rest, "분위기")),
            ("단체 가능(구글)", rest["good_for_groups"] == True),
        ],
    }[purpose]
    checks = checks + [(f"동료가 '{purpose}'로 다녀옴", rest["restaurant_id"].isin(went_for))]
    reasons = pd.Series([[] for _ in range(len(rest))], index=rest.index)
    for label, mask in checks:
        for i in rest.index[mask.fillna(False)]:
            reasons[i].append(label)
    return reasons


def recommend(meal_time, purpose, menus=None, max_walk=10, budget=None,
              only_confirmed=False, top_n=10):
    """조건에 맞는 식당을 점수 순으로 돌려준다. 결과 표와 '걸러진 이유' 메모를 함께 준다."""
    rest = load_restaurants()
    reviews = load_reviews()
    notes = []

    # ① 필수 조건. 확실히 안 되는 곳만 뺀다(빈칸은 남긴다).
    serve_col = "serves_lunch" if meal_time == "점심" else "serves_dinner"
    mask = rest[serve_col] != False
    if meal_time == "점심":
        mask &= rest["menu_category"] != "술집"
    if menus:
        mask &= rest["menu_category"].isin(expand_menus(menus))
    mask &= rest["walk_min"] <= max_walk
    if budget:
        # 최저 가격이 예산보다 비싼 곳만 뺀다. 가격 정보가 없으면 남긴다.
        mask &= ~(rest["price_min_won"] > budget)
    cand = rest[mask]

    cand = add_scores(cand, reviews, meal_time, purpose, rest["google_rating"].mean())
    cand["reasons"] = purpose_evidence(cand, purpose, reviews)
    cand["n_reasons"] = cand["reasons"].str.len()
    if only_confirmed and purpose != "편한 외식":
        before = len(cand)
        cand = cand[cand["n_reasons"] > 0]
        notes.append(f"'{purpose}' 근거가 없는 {before - len(cand)}곳은 뺐어요(정보가 없을 뿐 안 맞는다는 뜻은 아니에요).")

    # ③ 목적 가산점(최대 2개까지만 쳐서 정보가 많은 식당만 너무 유리해지지 않게 한다)
    cand["final"] = cand["score"] + PURPOSE_BONUS * cand["n_reasons"].clip(upper=2)
    cand = cand.sort_values(["final", "google_rating_count"], ascending=False)
    # 카카오에 이름만 다르게 두 번 올라온 같은 가게(구글 ID가 같음)는 한 번만 보여 준다
    dup = cand["google_place_id"].notna() & cand.duplicated("google_place_id")
    cand = cand[~dup]

    if cand.empty:
        notes.append(suggest_relax(rest, meal_time, menus, max_walk, budget))
    return cand.head(top_n), notes, len(cand)


def suggest_relax(rest, meal_time, menus, max_walk, budget):
    """결과가 0곳일 때 조건을 몰래 낮추지 않고, 무엇을 바꾸면 몇 곳이 생기는지 알려준다(17강)."""
    tips = []
    base = rest["menu_category"].isin(expand_menus(menus)) if menus else pd.Series(True, index=rest.index)
    wider = (base & (rest["walk_min"] <= max_walk + 5)).sum()
    if wider:
        tips.append(f"걸어서 {max_walk + 5}분까지 늘리면 {wider}곳")
    if budget:
        more = (base & (rest["walk_min"] <= max_walk) & ~(rest["price_min_won"] > budget + 10000)).sum()
        if more:
            tips.append(f"예산을 {budget + 10000:,}원으로 올리면 {more}곳")
    return "조건에 맞는 곳이 없어요. " + (", ".join(tips) + " 있어요." if tips else "메뉴를 더 골라 보세요.")


def explain(row):
    """카드에 보여 줄 '왜 추천했나요' 문장들."""
    lines = []
    if pd.notna(row["google_rating"]):
        lines.append(f"구글 별점 {row['google_rating']:.1f} (리뷰 {int(row['google_rating_count'])}개) → 보정 {row['google_score']:.2f}")
    else:
        lines.append("구글 별점: 정보 없음 (감점하지 않고 평균으로 둠)")
    if row["emp_count"] > 0:
        scope = "같은 목적" if row["emp_same_purpose"] else "다른 목적"
        lines.append(f"동료 리뷰 {row['emp_count']}개({scope}) 평균 {row['emp_mean']:.1f}")
    if row["reasons"]:
        lines.append("목적에 맞는 근거: " + ", ".join(row["reasons"]))
    return lines
