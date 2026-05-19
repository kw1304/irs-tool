"""
한국은행 ECOS API 기반 국고채 수익률 서버
GET /api/rates?date=YYYYMMDD

환경변수: ECOS_API_KEY  (https://ecos.bok.or.kr 에서 발급)
.env 파일 또는 시스템 환경변수로 설정
"""

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import os
import re
import logging

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

ECOS_BASE = "https://ecos.bok.or.kr/api/StatisticSearch"

# 817Y002 국고채수익률 실제 아이템코드 (StatisticItemList로 확인)
ITEM_MAP = {
    "010190000": "1Y",
    "010195000": "2Y",
    "010200000": "3Y",
    "010200001": "5Y",
    "010210000": "10Y",
    "010220000": "20Y",
    "010230000": "30Y",
}


# ──────────────────────────────────────────────────────────────────────────────
# 엔드포인트
# ──────────────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('.', 'IRS_평가툴_1.html')


@app.route('/api/rates', methods=['GET'])
def get_rates():
    date_str = request.args.get('date', '').strip()

    if not date_str:
        return jsonify({'success': False, 'error': 'date 파라미터가 필요합니다 (형식: YYYYMMDD)'}), 400

    if not re.fullmatch(r'\d{8}', date_str):
        return jsonify({'success': False, 'error': '날짜는 8자리 숫자여야 합니다 (예: 20240115)'}), 400

    try:
        datetime.strptime(date_str, '%Y%m%d')
    except ValueError:
        return jsonify({'success': False, 'error': '유효하지 않은 날짜입니다'}), 400

    api_key = os.environ.get('ECOS_API_KEY', '').strip()
    if not api_key:
        return jsonify({'success': False, 'error': 'ECOS_API_KEY 환경변수가 설정되지 않았습니다'}), 500

    try:
        rates, actual_date = fetch_govbond_rates(date_str, api_key)
    except requests.exceptions.Timeout:
        return jsonify({'success': False, 'error': 'ecos.bok.or.kr 응답 시간 초과'}), 504
    except requests.exceptions.ConnectionError:
        return jsonify({'success': False, 'error': 'ecos.bok.or.kr 연결 실패'}), 503
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 502
    except Exception as e:
        logger.exception("예기치 않은 오류")
        return jsonify({'success': False, 'error': str(e)}), 500

    if not rates:
        return jsonify({
            'success': False,
            'error': f'{date_str} 및 직전 5일 데이터 없음 (미래 날짜이거나 장기 연휴일 수 있습니다)'
        }), 404

    return jsonify({
        'success': True,
        'date': actual_date,
        'requested_date': date_str,
        'source': 'ecos.bok.or.kr',
        'rates': rates
    })


@app.route('/api/test', methods=['GET'])
def test_ecos():
    """ECOS API 직접 호출 테스트. ?item=010190000&date=YYYYMMDD 선택 가능."""
    api_key = os.environ.get('ECOS_API_KEY', '').strip()
    if not api_key:
        return jsonify({'success': False, 'error': 'ECOS_API_KEY 환경변수가 설정되지 않았습니다'}), 500

    item_code = request.args.get('item', '010190000').strip()   # 기본값: 1Y
    date_str  = request.args.get('date', datetime.today().strftime('%Y%m%d')).strip()

    url = (
        f"{ECOS_BASE}/{api_key}/json/kr/1/1"
        f"/817Y002/D/{date_str}/{date_str}/{item_code}"
    )

    result = {
        'success': False,
        'request': {'url': url.replace(api_key, '***'), 'item_code': item_code, 'date': date_str},
    }

    try:
        resp = requests.get(url, timeout=10)
        result['http_status'] = resp.status_code
        result['raw_response'] = resp.json()

        data = resp.json()
        if 'RESULT' in data:
            code = data['RESULT'].get('CODE', '')
            msg  = data['RESULT'].get('MESSAGE', '')
            result['ecos_code']    = code
            result['ecos_message'] = msg
            result['success']      = (code == 'INFO-200')   # 데이터 없음도 정상 케이스
            result['error']        = None if code == 'INFO-200' else f'ECOS 오류 {code}: {msg}'
        else:
            rows = data.get('StatisticSearch', {}).get('row', [])
            result['success']    = bool(rows)
            result['row_count']  = len(rows)
            result['first_row']  = rows[0] if rows else None
            result['error']      = None if rows else '행 없음 (INFO-200 아닌 빈 응답)'

    except requests.exceptions.Timeout:
        result['error'] = 'ecos.bok.or.kr 응답 시간 초과 (10s)'
    except requests.exceptions.ConnectionError as e:
        result['error'] = f'연결 실패: {e}'
    except ValueError as e:
        result['error'] = f'JSON 파싱 실패: {e}'
    except Exception as e:
        result['error'] = f'예기치 않은 오류: {e}'

    return jsonify(result), (200 if result['success'] else 502)


# ──────────────────────────────────────────────────────────────────────────────
# ECOS API 로직
# ──────────────────────────────────────────────────────────────────────────────

def fetch_govbond_rates(date_str: str, api_key: str) -> tuple:
    """ECOS에서 국고채 수익률 조회. 데이터 없으면 최대 5일 소급해 직전 영업일 반환."""
    target = datetime.strptime(date_str, '%Y%m%d')

    for delta in range(6):          # 당일(0) + 최대 5일 소급
        candidate = target - timedelta(days=delta)
        candidate_str = candidate.strftime('%Y%m%d')

        rates = _call_ecos(candidate_str, api_key)
        if rates:
            if delta > 0:
                logger.info("영업일 소급: %s → %s (%d일)", date_str, candidate_str, delta)
            return rates, candidate_str

    return {}, date_str


def _fetch_one(item_code: str, maturity: str, date_str: str, api_key: str) -> tuple:
    """만기 하나의 수익률을 ECOS에서 조회. (item_code, maturity, value | None) 반환."""
    url = (
        f"{ECOS_BASE}/{api_key}/json/kr/1/1"
        f"/817Y002/D/{date_str}/{date_str}/{item_code}"
    )
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    # INFO-200: 해당 날짜 데이터 없음 (휴장일 등) — 정상 케이스
    if 'RESULT' in data:
        code = data['RESULT'].get('CODE', '')
        msg  = data['RESULT'].get('MESSAGE', '')
        if code == 'INFO-200':
            return item_code, maturity, None
        raise ValueError(f'ECOS API 오류 {code}: {msg}')

    rows = data.get('StatisticSearch', {}).get('row', [])
    if not rows:
        return item_code, maturity, None

    value_str = rows[0].get('DATA_VALUE', '').strip()
    if not value_str:
        return item_code, maturity, None

    return item_code, maturity, round(float(value_str), 4)


def _call_ecos(date_str: str, api_key: str) -> dict:
    """7개 만기 아이템코드를 병렬 조회 → {만기: {ask, bid, mid}} 반환."""
    logger.info("ECOS 병렬 조회: date=%s", date_str)
    rates = {}

    with ThreadPoolExecutor(max_workers=len(ITEM_MAP)) as executor:
        futures = {
            executor.submit(_fetch_one, item_code, maturity, date_str, api_key): maturity
            for item_code, maturity in ITEM_MAP.items()
        }
        for future in as_completed(futures):
            try:
                _, maturity, value = future.result()
                if value is not None:
                    rates[maturity] = {'ask': None, 'bid': None, 'mid': value}
            except Exception as e:
                logger.warning("아이템 조회 실패: %s", e)

    return rates


# ──────────────────────────────────────────────────────────────────────────────
# 실행
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
