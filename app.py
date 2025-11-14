import streamlit as st
import requests
import json
from datetime import datetime

BASE_URL = "https://qf3.qfactory.biz:8000"

LOGIN_URL = f"{BASE_URL}/common/login/post-login"
STOCK_DETAIL_URL = f"{BASE_URL}/inv/stock-onhand-lot/detail-list"
WAREHOUSE_LIST_URL = f"{BASE_URL}/inv/warehouse/list"
STOCK_TRANSFER_LIST_URL = f"{BASE_URL}/inv/stock-transfer-warehouse/list"
STOCK_TRANSFER_LOT_LIST_URL = f"{BASE_URL}/inv/stock-transfer-warehouse/lot-list"
STOCK_TRANSFER_SAVE_URL = f"{BASE_URL}/inv/stock-transfer-warehouse/save"
STOCK_TRANSFER_TRANSFER_URL = f"{BASE_URL}/inv/stock-transfer-warehouse/transfer"


def parse_barcode(barcode: str):
    """
    바코드 예시:
      - 10A0001L5251114001500 -> LOT: 10A0001-L5-251114001, 수량: 500
      - 10A5000P525093000120 -> LOT: 10A5000-P5-250930001, 수량: 20

    규칙:
      - 품목코드: 앞 7자리
      - LOT NO: 품목코드(7) + '-' + 중간 2자리 + '-' + 뒤 9자리  (총 18자리 사용)
      - 수량: 그 이후 남는 나머지 전체 자리 수
    """
    code = barcode.strip()
    # LOT 구성(18자리) + 최소 1자리 수량 = 19자리 이상이어야 함
    if len(code) < 19:
        raise ValueError("바코드 길이가 올바르지 않습니다.")

    item_code = code[0:7]      # 품목코드
    mid = code[7:9]            # 중간 2자리
    tail = code[9:18]          # LOT 뒤 9자리
    qty_str = code[18:]        # LOT(18자리) 이후 남은 전체 = 수량

    lot_code = f"{item_code}-{mid}-{tail}"

    try:
        quantity = int(qty_str)
    except ValueError:
        raise ValueError("수량 부분을 숫자로 변환할 수 없습니다.")

    return item_code, lot_code, quantity


def create_mes_session():
    if "cookies" not in st.session_state or not st.session_state.cookies:
        raise RuntimeError("로그인 정보가 없습니다. 먼저 로그인해 주세요.")

    session = requests.Session()
    session.cookies.update(st.session_state.cookies)
    headers = {
        "Accept": "*/*",
        "Content-Type": "application/json",
        "Origin": "https://qf3.qfactory.biz",
        "Referer": "https://qf3.qfactory.biz/",
        "X-Requested-With": "XMLHttpRequest",
    }
    session.headers.update(headers)
    return session


def mes_post(url: str, payload: dict):
    session = create_mes_session()
    resp = session.post(url, json=payload, timeout=15)

    # 상태코드가 4xx/5xx 이면, MES 가 내려준 에러 내용을 그대로 올려보냄
    if resp.status_code >= 400:
        try:
            detail = resp.json()  # JSON 이면 그대로 파싱
        except ValueError:
            detail = resp.text    # JSON 아니면 text 그대로
        raise RuntimeError(f"{url} 요청 실패 (status={resp.status_code}): {detail}")

    data = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError("MES 응답 형식이 올바르지 않습니다.")

    # success == False 인 경우, 전체 응답을 디버그로 출력
    if data.get("success") is False:
        try:
            print("=== DEBUG MES ERROR RESPONSE ===")
            print(json.dumps(data, ensure_ascii=False))
            print("=== END DEBUG MES ERROR RESPONSE ===")
        except Exception:
            print("=== DEBUG MES ERROR RESPONSE (raw) ===")
            print(data)
            print("=== END DEBUG MES ERROR RESPONSE (raw) ===")
        msg = data.get("msg") or "MES 처리 중 오류가 발생했습니다."
        raise RuntimeError(msg)

    return data


def ensure_warehouse_master():
    if "warehouse_master" in st.session_state and st.session_state.warehouse_master:
        return

    company_id = st.session_state.company_id
    plant_id = st.session_state.plant_id

    payload = {
        "languageCode": "KO",
        "companyId": company_id,
        "plantId": plant_id,
        "enabledFlag": "",
        "warehouseCode": "",
        "warehouseName": "",
        "warehouseType": "",
        "outsideFlag": "",
        "partnerCode": "",
        "partnerName": "",
        "availableForLocationFlag": "",
        "poReceivingFlag": "",
        "wipProductionFlag": "",
        "shipmentInspectionFlag": "",
        "defectiveStockFlag": "",
        "wipProcessingFlag": "",
        "managementType": "",
        "inventoryAssetFlag": "",
        "start": 1,
        "page": 1,
        "limit": 100,
    }

    data = mes_post(WAREHOUSE_LIST_URL, payload)
    inner = data.get("data") or {}   # "data": null 인 경우도 대비
    if isinstance(inner, dict):
        wlist = inner.get("list") or []
    else:
        wlist = []
    master = {}
    for row in wlist:
        code = row.get("warehouseCode")
        if code:
            master[code] = row
    st.session_state.warehouse_master = master


def get_warehouse_info(code: str):
    ensure_warehouse_master()
    master = st.session_state.get("warehouse_master")  # warehouse_master 가 없거나 None 인 경우 대비
    if master is None:
        raise RuntimeError("창고 마스터(warehouse_master)가 초기화되지 않았습니다.")
    if not isinstance(master, dict):
        raise RuntimeError(f"창고 마스터 형식이 올바르지 않습니다: {type(master)}")
    info = master.get(code)
    if not info:
        raise RuntimeError(f"창고코드 {code} 에 해당하는 정보를 찾을 수 없습니다.")
    return info


def check_stock_by_lot(item_code: str, lot_code: str, warehouse_code: str):
    company_id = st.session_state.company_id
    plant_id = st.session_state.plant_id

    payload = {
        "languageCode": "KO",
        "companyId": company_id,
        "plantId": plant_id,
        "itemCode": "",  # itemCode 조건은 빼고 lotCode + warehouseCode 로만 조회
        "itemName": "",
        "itemType": "",
        "projectCode": "",
        "projectName": "",
        "productGroup": "",
        "itemClass1": "",
        "itemClass2": "",
        "warehouseCode": warehouse_code,
        "warehouseName": "",
        "warehouseLocationCode": "",
        "defectiveFlag": "Y",
        "itemClass3": "",
        "itemClass4": "",
        "effectiveDateFrom": "",
        "effectiveDateTo": "",
        "creationDateFrom": "",
        "creationDateTo": "",
        "lotStatus": "",
        "lotCode": lot_code,
        "jobName": "",
        "partnerItem": "",
        "peopleName": "",
        "start": 1,
        "page": 1,
        "limit": "40",
    }

    data = mes_post(STOCK_DETAIL_URL, payload)
    inner = data.get("data") or {}   # "data": null 인 경우 대비
    if isinstance(inner, dict):
        dlist = inner.get("list") or []
    else:
        dlist = []

    if not dlist:  # 조회 결과가 완전히 없으면 그대로 None 리턴
        return None

    # LOT + 창고코드 모두 일치
    for row in dlist:
        if row.get("lotCode") == lot_code and row.get("warehouseCode") == warehouse_code:
            return row

    # LOT 만 일치
    for row in dlist:
        if row.get("lotCode") == lot_code:
            return row

    # 그래도 못 찾으면 첫 번째 행
    return dlist[0]


def fetch_transfer_header(item_code: str, warehouse_code: str):
    company_id = st.session_state.company_id
    plant_id = st.session_state.plant_id

    payload = {
        "companyId": company_id,
        "plantId": plant_id,
        "warehouseCode": warehouse_code,
        "warehouseName": "",
        "locationCode": "",
        "locationName": "",
        "itemCode": item_code,
        "itemType": "",
        "itemTypeName": "",
        "productGroup": "",
        "productGroupName": "",
        "projectCode": "",
        "projectName": "",
        "itemName": "",
        "languageCode": "KO",
        "start": 1,
        "page": 1,
        "limit": "20",
    }

    data = mes_post(STOCK_TRANSFER_LIST_URL, payload)
    inner = data.get("data") or {}   # data 가 None 이거나 "data": null 인 경우 방어
    if isinstance(inner, dict):
        dlist = inner.get("list") or []
    else:
        dlist = []
    for row in dlist:
        if row.get("itemCode") == item_code and row.get("warehouseCode") == warehouse_code:
            return row
    return None


def fetch_transfer_lot_list(item_id: int, warehouse_id: int):
    company_id = st.session_state.company_id
    plant_id = st.session_state.plant_id

    payload = {
        "languageCode": "KO",
        "companyId": company_id,
        "plantId": plant_id,
        "itemId": item_id,
        "warehouseId": warehouse_id,
        "locationId": 0,
        "projectId": 0,
        "effectiveStartDate": "",
        "effectiveEndDate": "",
        "start": 1,
        "page": 1,
        "limit": 25,
    }

    data = mes_post(STOCK_TRANSFER_LOT_LIST_URL, payload)
    inner = data.get("data") or {}
    if isinstance(inner, dict):
        return inner.get("list") or []
    return []


def perform_transfer(rows, from_wh_code: str, to_wh_code: str):
    # 디버그용 Traceback + 주요 데이터 출력
    try:
        if not rows:
            st.warning("이동할 바코드가 없습니다.")
            return

        ensure_warehouse_master()
        to_wh_info = get_warehouse_info(to_wh_code)

        company_id = st.session_state.company_id
        plant_id = st.session_state.plant_id
        company_code = st.session_state.company_code
        language_code = "KO"

        now = datetime.now()
        transaction_date = now.strftime("%Y-%m-%d %H:%M:%S")
        period_date = now.strftime("%Y-%m")

        # 여러 개의 행이 있어도, MES 에는 행별로 1건씩 순차 전송
        for row in rows:
            item_code = row["itemCode"]
            lot_code = row["lotCode"]
            move_qty = row["quantity"]
            stock_row = row["stock_row"]

            header = fetch_transfer_header(item_code, from_wh_code)
            if not header:
                st.error(f"[{item_code}] / 창고 [{from_wh_code}] 의 재고 헤더 정보를 찾지 못했습니다.")
                return

            item_id = header.get("itemId")
            warehouse_id = header.get("warehouseId")

            lot_list = fetch_transfer_lot_list(item_id=item_id, warehouse_id=warehouse_id)
            lot_row = None
            for l in lot_list:
                if l.get("lotCode") == lot_code:
                    lot_row = l
                    break

            if not lot_row:
                st.error(f"LOT [{lot_code}] 의 창고이동 LOT 정보를 찾지 못했습니다.")
                return

            # 브라우저 SAVE payload 와 최대한 동일하게 맞추기
            header_obj = dict(header)

            # locationId / projectId 가 None 이면 0 으로 보정 (브라우저 payload 와 동일하게)
            header_obj["locationId"] = header.get("locationId") or 0
            header_obj["projectId"] = header.get("projectId") or 0

            # 거래수량 = LOT 이동수량 합계와 같아야 하므로, 기본단위수량(primaryQuantity)을 이동수량으로 맞춤
            header_obj["primaryQuantity"] = float(move_qty)

            # 프론트에서 사용하는 id / row-active 필드 추가 (서버가 참조할 수도 있으므로 형태만 맞춤)
            if "id" not in header_obj:
                header_obj["id"] = f"python-{item_code}-{lot_code}"
            header_obj["row-active"] = True

            # 목적 창고 정보
            header_obj["saveWarehouseId"] = to_wh_info.get("warehouseId")
            header_obj["saveWarehouseCode"] = to_wh_info.get("warehouseCode")
            header_obj["saveWarehouseName"] = to_wh_info.get("warehouseName")

            # 브라우저 payload 기준: saveLocationId / Code / Name 은 null 로 보냄
            header_obj["saveLocationId"] = None
            header_obj["saveLocationCode"] = None
            header_obj["saveLocationName"] = None

            header_obj["saveMoveQuantity"] = move_qty
            header_obj["editStatus"] = "U"
            header_obj["errorField"] = {}
            header_obj["transferWarehouseId"] = to_wh_info.get("warehouseId")
            header_obj["transactionTypeId"] = 10084
            header_obj["transactionDate"] = transaction_date
            header_obj["periodDate"] = period_date
            header_obj["availableForLocationFlag"] = header.get("availableForLocationFlag", "N")
            header_obj["transferLocationId"] = 0
            header_obj["lotCount"] = 1
            header_obj["transferItemId"] = header.get("itemId")
            header_obj["transferPlantId"] = header.get("plantId", plant_id)
            header_obj["webUrlId"] = 13648
            header_obj["interfaceFlag"] = "N"

            records_u = [header_obj]

            lot_obj = dict(lot_row)
            if "id" not in lot_obj:
                lot_obj["id"] = f"python-lot-{lot_obj.get('lotId') or lot_obj.get('lotCode')}"
            lot_obj["editStatus"] = "U"
            lot_obj["moveQuantity"] = float(move_qty)
            lot_obj["onhandStockId"] = header.get("onhandStockId")
            records_u2 = [lot_obj]

            payload = {
                "recordsI": json.dumps([], ensure_ascii=False),
                "recordsU": json.dumps(records_u, ensure_ascii=False),
                "recordsU2": json.dumps(records_u2, ensure_ascii=False),
                "recordsD": json.dumps([], ensure_ascii=False),
                "menuTreeId": "13648",
                "companyCode": company_code,
                "companyId": company_id,
                "languageCode": language_code,
            }

            # 디버그: SAVE 요청 payload를 콘솔에 출력
            print("=== DEBUG SAVE payload ===")
            try:
                print(json.dumps(payload, ensure_ascii=False))
            except Exception:
                print(payload)
            print("=== END DEBUG SAVE payload ===")

            save_data = mes_post(STOCK_TRANSFER_SAVE_URL, payload)
            if not isinstance(save_data, dict):
                raise RuntimeError(f"창고이동 SAVE 응답 형식이 올바르지 않습니다: {save_data!r}")

            # 디버그: SAVE 응답
            print("=== DEBUG SAVE response ===")
            try:
                print(json.dumps(save_data, ensure_ascii=False))
            except Exception:
                print(save_data)
            print("=== END DEBUG SAVE response ===")

            data_field = save_data.get("data")
            if isinstance(data_field, dict):
                transfer_tmp_id = data_field.get("list")  # {"list": 14720} 형태
            else:
                transfer_tmp_id = data_field
            if not transfer_tmp_id:
                st.error("save 처리 후 transferTmpId 를 받지 못했습니다.")
                return

            transfer_payload = {
                "companyId": company_id,
                "transferTmpId": transfer_tmp_id,
                "companyCode": company_code,
                "languageCode": language_code,
            }

            # 디버그: TRANSFER payload
            print("=== DEBUG TRANSFER payload ===")
            try:
                print(json.dumps(transfer_payload, ensure_ascii=False))
            except Exception:
                print(transfer_payload)
            print("=== END DEBUG TRANSFER payload ===")

            transfer_resp = mes_post(STOCK_TRANSFER_TRANSFER_URL, transfer_payload)

            # 디버그: TRANSFER 응답
            print("=== DEBUG TRANSFER response ===")
            try:
                print(json.dumps(transfer_resp, ensure_ascii=False))
            except Exception:
                print(transfer_resp)
            print("=== END DEBUG TRANSFER response ===")

        st.success("창고이동이 완료되었습니다.")
        st.session_state[f"transfer_rows_{from_wh_code}_{to_wh_code}"] = []
    except Exception:
        # 여기서 전체 Traceback 과 주요 상태를 PowerShell 에 출력
        import traceback
        print("========== PERFORM_TRANSFER DEBUG TRACEBACK ==========")
        traceback.print_exc()
        print("rows:", rows)
        print("from_wh_code:", from_wh_code, "to_wh_code:", to_wh_code)
        print("session_state keys:", list(st.session_state.keys()))
        print("========== END PERFORM_TRANSFER DEBUG TRACEBACK ==========")
        raise


def login_to_mes(user_id: str, password: str):
    payload = {
        "companyCode": "BWC40601",
        "userKey": user_id,
        "password": password,
        "languageCode": "KO",
    }

    session = requests.Session()
    headers = {
        "Accept": "*/*",
        "Content-Type": "application/json",
        "Origin": "https://qf3.qfactory.biz",
        "Referer": "https://qf3.qfactory.biz/",
        "X-Requested-With": "XMLHttpRequest",
    }
    session.headers.update(headers)

    resp = session.post(LOGIN_URL, json=payload, timeout=10)
    resp.raise_for_status()

    data = resp.json()
    if not isinstance(data, dict):
        msg = "로그인 응답 형식이 올바르지 않습니다."
        return False, msg, None, None

    if not data.get("success"):
        msg = data.get("msg") or "MES 서버에서 로그인 실패 응답을 받았습니다."
        return False, msg, None, None

    cookies = session.cookies.get_dict()
    user_info = data.get("userInfo", {})
    org_info = data.get("orgInfo", {})

    return True, data, cookies, {"userInfo": user_info, "orgInfo": org_info}


def init_session_state():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
    if "user_info" not in st.session_state:
        st.session_state.user_info = None
    if "org_info" not in st.session_state:
        st.session_state.org_info = None
    if "cookies" not in st.session_state:
        st.session_state.cookies = None
    if "current_page" not in st.session_state:
        st.session_state.current_page = "menu"
    if "warehouse_master" not in st.session_state:
        st.session_state.warehouse_master = None
    if "company_id" not in st.session_state:
        st.session_state.company_id = None
    if "plant_id" not in st.session_state:
        st.session_state.plant_id = None
    if "company_code" not in st.session_state:
        st.session_state.company_code = "BWC40601"


def apply_dark_theme():
    st.set_page_config(page_title="QFactory PDA", page_icon="📦", layout="centered")
    st.markdown(
        """
        <style>
        .stApp {
            background-color: #020617;
            color: #e5e7eb;
        }
        .stTextInput > div > div > input {
            background-color: #020617;
            color: #e5e7eb;
        }
        .stTextInput > div > div > input::placeholder {
            color: #6b7280;
        }
        .stButton > button {
            border-radius: 18px;
            padding: 1.2rem 1rem;
            font-size: 1.1rem;
            font-weight: 700;
            border: 1px solid #38bdf8;
            background: radial-gradient(circle at top left, #0ea5e9, #020617);
        }
        .stButton > button:hover {
            filter: brightness(1.1);
        }
        .big-menu button {
            height: 5rem;
            font-size: 1.4rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def show_login_page():
    st.title("QFactory PDA 로그인")
    st.write("ID / PW 를 입력해서 MES 에 로그인합니다.")

    with st.form("login_form"):
        user_id = st.text_input("ID", max_chars=50)
        password = st.text_input("PW", type="password")
        submitted = st.form_submit_button("로그인")

    if submitted:
        if not user_id or not password:
            st.error("ID 와 PW 를 모두 입력해 주세요.")
            return

        with st.spinner("MES 서버에 로그인 중..."):
            try:
                ok, result, cookies, infos = login_to_mes(user_id, password)
            except requests.exceptions.RequestException as e:
                st.error(f"네트워크 또는 서버 오류: {e}")
                return
            except ValueError:
                st.error("로그인 응답(JSON) 파싱에 실패했습니다.")
                return

        if not ok:
            st.error(f"로그인 실패: {result}")
            return

        st.session_state.logged_in = True
        st.session_state.cookies = cookies
        st.session_state.user_info = infos["userInfo"]
        st.session_state.org_info = infos["orgInfo"]
        st.session_state.company_id = infos["userInfo"].get("companyId")
        st.session_state.plant_id = infos["userInfo"].get("plantId")
        st.session_state.company_code = infos["userInfo"].get("companyCode", "BWC40601")
        st.session_state.current_page = "menu"

        st.success("로그인 성공!")
        st.rerun()


def show_main_menu():
    user_info = st.session_state.get("user_info") or {}
    user_name = user_info.get("userName") or ""
    company_name = user_info.get("companyName") or ""

    if user_name:
        st.markdown(f"**{user_name}** 님 환영합니다.")
    if company_name:
        st.caption(company_name)

    st.markdown("### PDA 메인 메뉴")

    st.markdown(
        """
        <div style="margin-top: 1.5rem;"></div>
        """,
        unsafe_allow_html=True,
    )

    container = st.container()
    with container:
        st.markdown('<div class="big-menu">', unsafe_allow_html=True)
        out_btn = st.button("임가공 출고 (1WP → 1JO)", use_container_width=True, key="btn_out")
        st.write("")
        in_btn = st.button("임가공 입고 (1JO → 1FGCK)", use_container_width=True, key="btn_in")
        st.write("")
        logout_btn = st.button("로그아웃", use_container_width=True, key="btn_logout")
        st.markdown("</div>", unsafe_allow_html=True)

    if out_btn:
        st.session_state.current_page = "outsourcing_out"
        st.rerun()

    if in_btn:
        st.session_state.current_page = "outsourcing_in"
        st.rerun()

    if logout_btn:
        for key in (
            "logged_in",
            "user_info",
            "org_info",
            "cookies",
            "current_page",
            "warehouse_master",
            "company_id",
            "plant_id",
        ):
            if key in st.session_state:
                del st.session_state[key]
        st.success("로그아웃 되었습니다.")
        st.rerun()


def show_transfer_page(mode: str):
    if mode == "out":
        title = "임가공 출고 (1WP → 1JO)"
        from_wh = "1WP"
        to_wh = "1JO"
    else:
        title = "임가공 입고 (1JO → 1FGCK)"
        from_wh = "1JO"
        to_wh = "1FGCK"

    rows_key = f"transfer_rows_{from_wh}_{to_wh}"
    if rows_key not in st.session_state:
        st.session_state[rows_key] = []

    st.markdown(f"### {title}")
    st.caption(f"From 창고: {from_wh} / To 창고: {to_wh}")

    barcode_key = f"barcode_input_{from_wh}_{to_wh}"

    def handle_barcode_scan():
        raw = st.session_state.get(barcode_key, "").strip()
        if not raw:
            return

        try:
            item_code, lot_code, quantity = parse_barcode(raw)
        except ValueError as e:
            st.error(str(e))
            st.session_state[barcode_key] = ""
            return

        try:
            stock_row = check_stock_by_lot(item_code=item_code, lot_code=lot_code, warehouse_code=from_wh)
        except Exception as e:
            st.error(f"재고조회 중 오류: {e}")
            st.session_state[barcode_key] = ""
            return

        if not stock_row:
            st.error("From 창고에 해당 LOT 재고가 없습니다.")
            st.session_state[barcode_key] = ""
            return

        onhand_qty = stock_row.get("onhandQuantity", 0)
        try:
            onhand_qty_float = float(onhand_qty)
        except Exception:
            onhand_qty_float = 0

        if quantity > onhand_qty_float:
            st.error(f"From 창고 재고부족: LOT 재고 {onhand_qty_float}, 이동요청 {quantity}")
            st.session_state[barcode_key] = ""
            return

        new_row = {
            "barcode": raw,
            "itemCode": item_code,
            "lotCode": lot_code,
            "quantity": quantity,
            "fromWarehouse": from_wh,
            "toWarehouse": to_wh,
            "onhandQuantity": onhand_qty_float,
            "itemName": stock_row.get("itemName"),
            "warehouseName": stock_row.get("warehouseName"),
            "uom": stock_row.get("primaryUom"),
            "stock_row": stock_row,
        }

        st.session_state[rows_key].append(new_row)
        st.session_state[barcode_key] = ""

    st.text_input(
        "바코드 스캔",
        key=barcode_key,
        placeholder="PDA 로 바코드를 스캔해 주세요.",
        on_change=handle_barcode_scan,
    )

    st.markdown(
        f"""
        <script>
        const elements = window.parent.document.querySelectorAll('input[type="text"]');
        for (let i = 0; i < elements.length; i++) {{
            const el = elements[i];
            if (el.getAttribute('aria-label') === '바코드 스캔') {{
                el.focus();
                el.select();
                break;
            }}
        }}
        </script>
        """,
        unsafe_allow_html=True,
    )

    rows = st.session_state[rows_key]

    st.markdown("#### 스캔 목록")
    if rows:
        table_data = []
        for idx, r in enumerate(rows, start=1):
            table_data.append(
                {
                    "No": idx,
                    "품목코드": r["itemCode"],
                    "품목명": r.get("itemName"),
                    "LOT NO": r["lotCode"],
                    "수량": r["quantity"],
                    "From 창고": r["fromWarehouse"],
                    "To 창고": r["toWarehouse"],
                    "From 재고": r["onhandQuantity"],
                    "단위": r.get("uom"),
                }
            )

        st.dataframe(table_data, use_container_width=True)

        delete_index = None
        if len(rows) > 0:
            idx_options = list(range(1, len(rows) + 1))
            selected_no = st.selectbox("삭제할 행 번호 선택", idx_options)
            delete_index = selected_no - 1

        col_left, col_center, col_right = st.columns([1, 1, 2])
        with col_left:
            if st.button("삭제", key=f"btn_delete_{from_wh}_{to_wh}"):
                if delete_index is not None and 0 <= delete_index < len(st.session_state[rows_key]):
                    st.session_state[rows_key].pop(delete_index)
                    st.success("선택한 행을 삭제했습니다.")
                    st.rerun()
        with col_center:
            if st.button("초기화", key=f"btn_reset_{from_wh}_{to_wh}"):
                st.session_state[rows_key] = []
                st.success("스캔 목록을 초기화했습니다.")
                st.rerun()
        with col_right:
            if st.button("창고이동", key=f"btn_transfer_{from_wh}_{to_wh}"):
                try:
                    perform_transfer(rows, from_wh_code=from_wh, to_wh_code=to_wh)
                except Exception as e:
                    st.error(f"창고이동 처리 중 오류: {e}")
    else:
        st.info("스캔된 바코드가 없습니다. 바코드를 스캔해 주세요.")

    if st.button("◀ 메인 메뉴로", key=f"btn_back_{from_wh}_{to_wh}"):
        st.session_state.current_page = "menu"
        st.rerun()


def main():
    apply_dark_theme()
    init_session_state()

    if not st.session_state.logged_in:
        show_login_page()
        return

    page = st.session_state.current_page
    if page == "menu":
        show_main_menu()
    elif page == "outsourcing_out":
        show_transfer_page("out")
    elif page == "outsourcing_in":
        show_transfer_page("in")
    else:
        show_main_menu()


if __name__ == "__main__":
    main()
