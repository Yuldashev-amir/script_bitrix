import requests
import time
from load_dotenv import dotenv
import os
WEBHOOK_URL = "http://127.0.0.1:5000/process"
ACCESS_TOKEN = TOKEN_BITRIX

def process_all_deals():
    """Получает все сделки из Битрикс24 и отправляет на обработку"""
    

    bitrix_webhook = "https://ВАШ_ПОРТАЛ.bitrix24.ru/rest/1/process_all/"
    
    print("Получаем список сделок...")
    response = requests.post(f"{bitrix_webhook}crm.deal.list.json", json={
        "select": ["ID", "COMPANY_ID"],
        "filter": {"!COMPANY_ID": ""},
        "order": {"ID": "ASC"}
    })
    
    deals = response.json().get("result", [])
    print(f"Найдено сделок: {len(deals)}")
    
    
    success = 0
    errors = 0
    
    for i, deal in enumerate(deals):
        deal_id = deal["ID"]
        print(f"[{i+1}/{len(deals)}] Обработка сделки {deal_id}...")
        
        try:
            result = requests.post(
                WEBHOOK_URL,
                json={"deal_id": deal_id},
                headers={"X-Access-Token": ACCESS_TOKEN},
                timeout=30
            )
            
            if result.status_code == 200:
                success += 1
                print(f"  ✅ Успешно")
            else:
                errors += 1
                print(f"  ❌ Ошибка: {result.status_code}")
                
        except Exception as e:
            errors += 1
            print(f"  ❌ Ошибка: {e}")
        
        
        time.sleep(0.5)
    
    print(f"\n=== ИТОГО ===")
    print(f"Успешно: {success}")
    print(f"Ошибок: {errors}")
    print(f"Всего: {len(deals)}")

if __name__ == "__main__":
    process_all_deals()
