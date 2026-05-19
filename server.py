"""
금융투자협회 채권정보센터(kofiabond.or.kr) 국고채 수익률 스크래핑 서버
GET /api/rates?date=YYYYMMDD
"""

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
from xml.etree import ElementTree as ET
from datetime import datetime
import re
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

KOFIA_URL = "https://www.kofiabond.or.kr/proframeWeb/XMLSERVICES/"

# 국고채 만기 매핑 (kofiabond 응답에서 사용되는 명칭 → 표준 키)
GOVBOND_MAP = {
    "국고채권(1년)":  "1Y",
    "국고채권(2년)":  "2Y",
    "국고채권(3년)":  "3Y",
    "국고채권(5년)":  "5Y",
    "국고채권(10년)": "10Y",
    "국고채권(20년)": "20Y",
    "국고채권(30년)": "30Y",
    "국고채권(50년)": "50Y",
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

    # 파라미터 검증
    if not date_str:
        return jsonify({'success': False, 'error': 'date 파라미터가 필요합니다 (형식: YYYYMMDD)'}), 400

    if not re.fullmatch(r'\d{8}', date_str):
        return jsonify({'success': False, 'error': '날짜는 8자리 숫자여야 합니다 (예: 20240115)'}), 400

    try:
        datetime.strptime(date_str, '%Y%m%d')
    except ValueError:
        return jsonify({'success': False, 'error': '유효하지 않은 날짜입니다'}), 400

    try:
        rates = fetch_govbond_rates(date_str)
    except requests.exceptions.Timeout:
        return jsonify({'success': False, 'error': 'kofiabond.or.kr 응답 시간 초과'}), 504
    except requests.exceptions.ConnectionError:
        return jsonify({'success': False, 'error': 'kofiabond.or.kr 연결 실패'}), 503
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 502
    except Exception as e:
        logger.exception("예기치 않은 오류")
        return jsonify({'success': False, 'error': str(e)}), 500

    if not rates:
        return jsonify({
            'success': False,
            'error': f'{date_str} 날짜의 데이터가 없습니다 (휴장일이거나 미래 날짜일 수 있습니다)'
        }), 404

    return jsonify({
        'success': True,
        'date': date_str,
        'source': 'kofiabond.or.kr',
        'rates': rates
    })


# ──────────────────────────────────────────────────────────────────────────────
# 스크래핑 로직
# ──────────────────────────────────────────────────────────────────────────────

def build_xml(date_str: str) -> bytes:
    """kofiabond XMLSERVICES 요청 바디 생성"""
    xml = (
        "<?xml version='1.0' encoding='utf-8'?>"
        "<message>"
        "<proframeHeader>"
        "<pfmAppName>BIS-KOFIABOND</pfmAppName>"
        "<pfmSvcName>BISLastAskPrcROPSrchSO</pfmSvcName>"
        "<pfmFnName>listDay</pfmFnName>"
        "</proframeHeader>"
        "<systemHeader></systemHeader>"
        f"<BISComDspDatDTO><val1>{date_str}</val1></BISComDspDatDTO>"
        "</message>"
    )
    return xml.encode('utf-8')


def fetch_govbond_rates(date_str: str) -> dict:
    """kofiabond.or.kr에서 국고채 수익률을 가져와 {만기: 수익률} 딕셔너리 반환"""
    headers = {
        'Content-Type': 'application/xml; charset=utf-8',
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/124.0.0.0 Safari/537.36'
        ),
        'Referer': 'https://www.kofiabond.or.kr/',
        'Origin':  'https://www.kofiabond.or.kr',
    }

    session = requests.Session()

    # 세션 쿠키 획득 (HTTPS)
    try:
        session.get('https://www.kofiabond.or.kr/', timeout=10,
                    headers={'User-Agent': headers['User-Agent']})
    except Exception:
        pass  # 쿠키 없어도 진행

    logger.info("kofiabond 요청: date=%s", date_str)
    resp = session.post(KOFIA_URL, data=build_xml(date_str), headers=headers, timeout=15)
    resp.raise_for_status()

    logger.debug("응답 내용: %s", resp.text[:500])
    return parse_xml(resp.text)


def parse_xml(xml_text: str) -> dict:
    """XML 응답에서 국고채 수익률 추출

    kofiabond BISLastAskPrcROPSrchSO 응답 필드:
      val1 = 채권명 (예: 국고채권(3년))
      val3 = 매도 호가 수익률
      val4 = 매수 호가 수익률
      val5 = 전일 대비 변동
    """
    try:
        root = ET.fromstring(xml_text.encode('utf-8'))
    except ET.ParseError as e:
        raise ValueError(f'XML 파싱 오류: {e}')

    rates = {}

    for dto in root.findall('.//BISComDspDatDTO'):
        vals = {c.tag: (c.text or '').strip() for c in dto}

        bond_name = vals.get('val1', '')
        ask_str   = vals.get('val3', '')
        bid_str   = vals.get('val4', '')

        if not bond_name:
            continue

        maturity = GOVBOND_MAP.get(bond_name)
        if maturity is None:
            for key, mat in GOVBOND_MAP.items():
                if bond_name in key or key in bond_name:
                    maturity = mat
                    break

        if maturity is None:
            continue

        try:
            ask = round(float(ask_str), 4) if ask_str else None
            bid = round(float(bid_str), 4) if bid_str else None
            mid = round((ask + bid) / 2, 4) if (ask is not None and bid is not None) else None
            rates[maturity] = {'ask': ask, 'bid': bid, 'mid': mid}
        except ValueError:
            logger.warning("수익률 파싱 실패: bond=%s ask=%s bid=%s", bond_name, ask_str, bid_str)

    return rates


# ──────────────────────────────────────────────────────────────────────────────
# 실행
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
