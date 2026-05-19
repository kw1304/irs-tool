"""
한국은행 ECOS API 기반 국고채 수익률 서버
GET /api/rates?date=YYYYMMDD

환경변수: ECOS_API_KEY  (https://ecos.bok.or.kr 에서 발급)
.env 파일 또는 시스템 환경변수로 설정
"""

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
from datetime import datetime, timedelta
import os
import re
import logging

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

ECOS_BASE = "https://ecos.bok.or.kr/api/StatisticSearch"

# 817Y002 국고채수익률 아이템코드 → 표준 만기 키
ITEM_MAP = {
    "010190000": "1Y",
    "010200000": "2Y",
    "010210000": "3Y",
    "010220000": "5Y",
    "010230000": "10Y",
    "010240000": "20Y",
    "010250000": "30Y",
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


def _call_ecos(date_str: str, api_key: str) -> dict:
    """ECOS StatisticSearch 단일 날짜 호출 → {만기: {ask, bid, mid}} 반환"""
    url = (
        f"{ECOS_BASE}/{api_key}/json/kr/1/100"
        f"/817Y002/DD/{date_str}/{date_str}"
    )
    logger.info("ECOS 요청: date=%s", date_str)

    resp = requests.get(url, timeout=10)
    resp.raise_for_status()

    data = resp.json()

    # ECOS는 오류 시 'RESULT' 키로 응답
    if 'RESULT' in data:
        code = data['RESULT'].get('CODE', '')
        msg  = data['RESULT'].get('MESSAGE', '')
        # CODE-100: 데이터 없음(정상), 그 외는 진짜 오류
        if code != 'CODE-100':
            raise ValueError(f'ECOS API 오류 {code}: {msg}')
        return {}

    rows = data.get('StatisticSearch', {}).get('row', [])
    if not rows:
        return {}

    rates = {}
    for row in rows:
        item_code = row.get('ITEM_CODE1', '')
        value_str = row.get('DATA_VALUE', '').strip()

        maturity = ITEM_MAP.get(item_code)
        if not maturity or not value_str:
            continue

        try:
            mid = round(float(value_str), 4)
            rates[maturity] = {'ask': None, 'bid': None, 'mid': mid}
        except ValueError:
            logger.warning("수익률 파싱 실패: item=%s value=%s", item_code, value_str)

    return rates


# ──────────────────────────────────────────────────────────────────────────────
# 실행
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
