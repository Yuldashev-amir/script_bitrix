from flask import Flask, request, jsonify
import requests
import logging
import time
from dotenv import load_dotenv
import os
from datetime import datetime


WEBHOOK_URL = "https://your-domain.bitrix24.ru/rest/137594/TOKEN_BITRIX/"

FIELD_SHARE_DEAL = "UF_CRM_1775043174885"      
FIELD_PREVIOUS_SHARE = "UF_CRM_1775213734543"  
FIELD_SHARE_COMPANY = "UF_CRM_1728655866104"   


PROJECT_GROWTH = 154  
PROJECT_DECLINE = 152  

STAGE_ID_20 = "C13:UC_6YP8H1"
STAGE_ID_40 = "C13:UC_86QVZI"
STAGE_ID_60 = "C13:UC_5N3WU7" 
STAGE_ID_80 = "C13:UC_LCMO2X"  
STAGE_ID_80_PLUS = "C13:UC_LRU35Z" 

TEST_MODE = False 

ACCESS_TOKEN = ""

CATEGORY_ID = 13  

load_dotenv()

ACCESS_TOKEN = os.getenv(TOKEN_BITRIX)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bitrix_webhook.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)


def call_bitrix(method, params=None):
    url = f"{WEBHOOK_URL}{method}.json"
    try:
        response = requests.post(url, json=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Ошибка API {method}: {e}")
        return None


def get_target_stage_by_share(share_percent):
    if share_percent < 20:
        return None
    elif share_percent < 40:
        return STAGE_ID_40
    elif share_percent < 60:
        return STAGE_ID_60
    elif share_percent < 80:
        return STAGE_ID_80
    else:
        return STAGE_ID_80_PLUS


def process_deal(deal_id):
    logger.info(f"=" * 50)
    logger.info(f"Обработка сделки {deal_id}")
    

    deal = call_bitrix("crm.deal.get", {"id": deal_id})
    if not deal or not deal.get("result"):
        logger.error(f"Сделка {deal_id} не найдена")
        return {"success": False, "error": "Deal not found"}



    responsible_id = deal["result"].get("ASSIGNED_BY_ID")
    if not responsible_id:
        responsible_id = 1 
        logger.warning(f"⚠️ В сделке {deal_id} не указан ответственный, задача создаётся на администратора")
    else:
        logger.info(f"Ответственный по сделке: {responsible_id}")
    
    company_id = deal["result"].get("COMPANY_ID")
    if not company_id:
        logger.error(f"К сделке не привязана компания")
        return {"success": False, "error": "No company"}
    
    current_stage = deal["result"].get("STAGE_ID")
    logger.info(f"Текущая стадия: {current_stage}")
    
    company = call_bitrix("crm.company.get", {"id": company_id})
    if not company or not company.get("result"):
        logger.error(f"Компания {company_id} не найдена")
        return {"success": False, "error": "Company not found"}
    
    company_name = company["result"].get("TITLE", "Unknown")
    
    try:
        company_share_val = company["result"].get(FIELD_SHARE_COMPANY)
        current_share_val = deal["result"].get(FIELD_SHARE_DEAL)
        previous_share_val = deal["result"].get(FIELD_PREVIOUS_SHARE)
        
        company_share = float(company_share_val) if company_share_val not in (None, '', 'None') else None
        current_share = float(current_share_val) if current_share_val not in (None, '', 'None') else None
        previous_share = float(previous_share_val) if previous_share_val not in (None, '', 'None') else None
    except (ValueError, TypeError) as e:
        logger.error(f"Ошибка преобразования в число: {e}")
        return {"success": False, "error": f"Invalid number: {e}"}
    
    logger.info(f"Компания: {company_name}")
    logger.info(f"Доля в сделке (было): {current_share}%")
    logger.info(f"Доля в компании (стало): {company_share}%")
    logger.info(f"Предыдущая доля (до прошлого): {previous_share}%")
    
    if company_share is None:
        logger.warning(f"В компании не заполнена доля")
        return {"success": False, "error": "Company share is empty"}
    
    if current_share == company_share:
        logger.info(f"Доли совпадают, обновление не требуется")
        return {"success": True, "action": "skipped"}
    
    has_previous = previous_share is not None
    has_current = current_share is not None
    
    base_share = 0
    if has_previous:
        base_share = previous_share
    elif has_current:
        base_share = current_share
    
    if base_share == 0 and not has_previous and not has_current:
        is_increase = True
        logger.info(f"Первое заполнение доли: 0% → {company_share}%")
    else:
        is_increase = company_share > base_share
    
    old_for_percent = base_share if base_share > 0 else (current_share if current_share else 0)
    if old_for_percent and old_for_percent > 0:
        change_percent = ((company_share - old_for_percent) / old_for_percent) * 100
    else:
        change_percent = 0
    
    logger.info(f"Динамика: {'РОСТ+' if is_increase else 'ПАДЕНИЕ-'} на {abs(change_percent):.1f}% (база: {base_share}%)")
    
    if not TEST_MODE:
        logger.info(f"🔄 Обновляем поля: Доля {current_share}% → {company_share}%")
        
        update_result = call_bitrix("crm.deal.update", {
            "id": deal_id,
            "fields": {
                FIELD_SHARE_DEAL: company_share,
                FIELD_PREVIOUS_SHARE: current_share if current_share else 0
            }
        })
        
        if not update_result or not update_result.get("result"):
            logger.error(f"Ошибка обновления: {update_result}")
            return {"success": False, "error": "Update failed"}
        
        logger.info(f"✅ Доля обновлена")
        

        if is_increase:
            target_stage = get_target_stage_by_share(company_share)
            
            if target_stage and target_stage != current_stage:
                logger.info(f"🔄 Меняем стадию: {current_stage} → {target_stage} (новая доля {company_share}%)")
                
                stage_result = call_bitrix("crm.deal.update", {
                    "id": deal_id,
                    "fields": {
                        "CATEGORY_ID": CATEGORY_ID,
                        "STAGE_ID": target_stage
                    }
                })
                
                if stage_result and stage_result.get("result"):
                    check_deal = call_bitrix("crm.deal.get", {"id": deal_id})
                    new_stage = check_deal.get("result", {}).get("STAGE_ID")
                    if new_stage == target_stage:
                        logger.info(f"✅ Стадия изменена на {target_stage}")
                    else:
                        logger.warning(f"⚠️ API сообщил об успехе, но стадия осталась {new_stage}")
                else:
                    logger.error(f"Ошибка смены стадии: {stage_result}")
            else:
                if target_stage is None:
                    logger.info(f"📊 Стадия не меняется (новая доля {company_share}% < 20% или нет целевой стадии)")
                elif target_stage == current_stage:
                    logger.info(f"📊 Стадия не меняется (уже на целевой стадии {target_stage})")
        else:
            logger.info(f"📉 ПАДЕНИЕ доли → стадия НЕ меняется")
        
        direction = "рост" if is_increase else "падение"
        project_id = PROJECT_GROWTH if is_increase else PROJECT_DECLINE
        
        logger.info(f"📝 Создаём задачу в проекте: {'растущие' if is_increase else 'отрицательный рост'}")
        logger.info(f"👤 Ответственный: {responsible_id}")
        
        task_title = f"{'📈' if is_increase else '📉'} {direction.capitalize()} доли: {int(old_for_percent)}% → {int(company_share)}%"
        
        task_result = call_bitrix("tasks.task.add", {
            "fields": {
                "TITLE": task_title,
                "DESCRIPTION": f"""Компания: {company_name}
                Доля {direction} с {int(old_for_percent)}% до {int(company_share)}% ({abs(change_percent):.1f}%)

                Сделка: https://cdek2023.bitrix24.ru/crm/deal/details/{deal_id}/

                Автоматически создано при изменении доли.""",
                "GROUP_ID": project_id,
                "RESPONSIBLE_ID": responsible_id,
                "UF_CRM_TASK": [f"D_{deal_id}"]
            }
        })
        
        if task_result and task_result.get("result"):
            task_id = task_result["result"].get("task", {}).get("id")
            logger.info(f"✅ Задача создана (ID: {task_id}) для ответственного {responsible_id}")
        else:
            logger.error(f"Ошибка создания задачи: {task_result}")
    
    else:
        logger.info(f"🔧 [ТЕСТ] Было бы обновление: {current_share}% → {company_share}%")
        if is_increase:
            target_stage = get_target_stage_by_share(company_share)
            if target_stage:
                logger.info(f"🔧 [ТЕСТ] Была бы смена стадии: {current_stage} → {target_stage}")
        logger.info(f"🔧 [ТЕСТ] Была бы создана задача в проекте {'растущие' if is_increase else 'отрицательный'}")
    
    return {"success": True, "action": "updated" if not TEST_MODE else "test"}


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})


@app.route('/process', methods=['POST'])
def process_one():
    try:
        token = request.headers.get('X-Access-Token')
        if token != ACCESS_TOKEN:
            return jsonify({"error": "Unauthorized"}), 401
        
        data = request.json
        deal_id = data.get('deal_id')
        if not deal_id:
            return jsonify({"error": "deal_id required"}), 400
        
        result = process_deal(deal_id)
        return jsonify(result)
    
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route('/process_all', methods=['POST'])
def process_all():
    try:
        token = request.headers.get('X-Access-Token')
        if token != ACCESS_TOKEN:
            return jsonify({"error": "Unauthorized"}), 401
        
        data = request.json or {}
        category_id = data.get('category_id')
        stage_id = data.get('stage_id')
        
        deal_filter = {"!COMPANY_ID": ""}
        if category_id is not None:
            deal_filter["CATEGORY_ID"] = category_id
        if stage_id:
            deal_filter["STAGE_ID"] = stage_id
        
        logger.info(f"=== МАССОВАЯ ОБРАБОТКА ===")
        logger.info(f"Фильтр: {deal_filter}")
        
        deals = call_bitrix("crm.deal.list", {
            "select": ["ID"],
            "filter": deal_filter,
            "order": {"ID": "ASC"}
        })
        
        if not deals or not deals.get("result"):
            logger.info("Сделок для обработки не найдено")
            return jsonify({"success": True, "processed": 0})
        
        results = []
        success_count = 0
        
        for deal in deals["result"]:
            result = process_deal(deal["ID"])
            time.sleep(0.4)
            if result.get("success"):
                success_count += 1
            results.append({
                "deal_id": deal["ID"],
                "success": result.get("success", False),
                "action": result.get("action")
            })
        
        logger.info(f"=== МАССОВАЯ ОБРАБОТКА ЗАВЕРШЕНА ===")
        logger.info(f"Успешно: {success_count}, Всего: {len(results)}")
        
        return jsonify({
            "success": True,
            "processed": len(results),
            "success_count": success_count,
            "results": results
        })
    
    except Exception as e:
        logger.error(f"Ошибка массовой обработки: {e}")
        return jsonify({"error": str(e)}), 500



@app.route('/debug_stages', methods=['GET'])
def debug_stages():
     """Получить полные коды статусов для воронки"""
     entity_id = f"DEAL_STAGE_{CATEGORY_ID}"
     stages = call_bitrix("crm.status.list", {
         "filter": {"ENTITY_ID": entity_id}
      })
     if stages and stages.get("result"):
        stage_list = [
             {
                 "id": s["STATUS_ID"],
                 "name": s["NAME"],
                 "sort": s["SORT"]
             }
            for s in stages["result"]
        ]
        return jsonify({"entity": entity_id, "stages": stage_list})
     return jsonify({"error": "Stages not found"})


if __name__ == '__main__':
    print("=" * 60)
    print("ЗАПУСК WEBHOOK СЕРВЕРА")
    print(f"Режим: {'🔧 ТЕСТОВЫЙ' if TEST_MODE else '🔥 БОЕВОЙ'}")
    print("=" * 60)
    app.run(host='127.0.0.1', port=5000, debug=True)
