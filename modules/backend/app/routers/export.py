from dependencies import get_db, get_current_user, verify_admin, log_audit_action
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional
import pandas as pd
import io
import database
from datetime import datetime

router = APIRouter(tags=["報表匯出模組"])

# openpyxl 看到 "=" 開頭的字串就把儲存格寫成真的公式（<f> 元素），
# 不是文字。實測 openpyxl 3.1.5：
#
#     "=cmd|'/c calc'!A1"  →  <c r="A2"><f>cmd|'/c calc'!A1</f><v /></c>
#
# 承辦人員開這個檔案時 Excel 會去執行它（DDE）。而 url 欄位是從
# /api/crawler/report/、/api/nlp/report/、/api/ai_result/report/ 寫進來的，
# 那三支只驗長度不驗 scheme（只有 /api/scan_target/ 的 FrontendScanRequest
# 會驗 http/https），所以 "=" 開頭的值進得了資料庫。
#
# 那三支要 internal token，外人打不到——但這個檔案是整套系統裡唯一一條
# 「資料離開系統邊界」的路徑，而且是拿去給人開的。token 存在五個容器裡，
# 任何一個被打下來就到得了這裡，理由跟 SEC-16 為什麼要驗欄位長度是同一個。
#
# 不用「前面加一撇」那種常見寫法：那會把 '=... 真的寫進值裡，網址就不是
# 當時抓到的那個網址了。改成明確標記型別為文字，並套上 quotePrefix——
# 那正是 Excel 自己用來表示「像公式的文字」的方式，值一個位元都不會動。
# 順帶把 #REF! 這類錯誤碼（openpyxl 會標成 data_type "e"）一起收掉。
def _disarm_formula_cells(ws):
    """把被推斷成公式／錯誤碼的儲存格改回文字，值不變。"""
    for row in ws.iter_rows():
        for cell in row:
            if cell.data_type in ("f", "e"):
                cell.data_type = "s"
                cell.quotePrefix = True


@router.get("/api/export/ai_results_excel/", summary="匯出 AI 分析結果資料表")
def export_raw_results_to_excel(
    start_date: Optional[str] = Query(None, max_length=32, description="開始日期 (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, max_length=32, description="結束日期 (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    # 匯出是把「全部蒐證資料」一次帶走，不是一般查詢——限管理員（SEC-12）。
    # 原本是 get_current_user，任何登入者都能整包下載。
    current_user = Depends(verify_admin),
): 
    query = db.query(
        database.AIAnalysisResult.id,
        database.AIAnalysisResult.url,
        database.AIAnalysisResult.risk_level,
        # 文字與影像分數分開取，不用合成的 risk_score
        database.AIAnalysisResult.nlp_score,
        database.AIAnalysisResult.yolo_score,
        database.AIAnalysisResult.created_at
    )
    
    # 日期一定要先驗格式再丟進查詢。
    # 沒驗的話 start_date="' OR 1=1--" 會讓 MySQL 在比較時丟例外，
    # 整個請求 500——雖然 SQLAlchemy 有參數化、注入不會成立，
    # 但把使用者輸入直接當日期比較本來就會炸，而且 500 對使用者毫無資訊。
    def _as_date(value: str, field: str) -> str:
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"{field} 的格式不正確，要 YYYY-MM-DD（收到：{value[:30]}）",
            )

    if start_date:
        query = query.filter(
            database.AIAnalysisResult.created_at >= _as_date(start_date, "start_date"))
    if end_date:
        query = query.filter(
            database.AIAnalysisResult.created_at
            <= f"{_as_date(end_date, 'end_date')} 23:59:59")
        
    results = query.all()
    
    if not results:
        raise HTTPException(status_code=404, detail="目前沒有符合該時間區間的分析資料可以匯出")

    # 兩個分數分開列。等級是二維判斷（文字夠高、影像有沒有附和），
    # 只給一個合成分數的話，報表上會出現「同樣 100 分卻是不同等級」。
    data_list = [
        {
            "案件編號": row.id,
            "網址": row.url,
            "風險等級": row.risk_level,
            "文字分數": row.nlp_score,
            "影像分數": row.yolo_score,
            "發現時間": row.created_at.strftime("%Y-%m-%d %H:%M:%S") if row.created_at else "",
        }
        for row in results
    ]

    df = pd.DataFrame(data_list)
    
    stream = io.BytesIO()
    
    with pd.ExcelWriter(stream, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='AI分析總表')
        # 要在 with 區塊「之內」處理：檔案是離開這個區塊時才序列化的，
        # 在外面改已經來不及了。
        _disarm_formula_cells(writer.sheets['AI分析總表'])
    
    stream.seek(0)

    # 「誰在什麼時候把整批蒐證資料帶走了」——這是稽核軌跡裡最該留的一筆
    log_audit_action(
        db, current_user.user_id, "匯出報表",
        f"匯出 {len(data_list)} 筆 AI 分析結果"
        + (f"（{start_date} ~ {end_date}）" if start_date or end_date else ""),
    )

    headers = {
        'Content-Disposition': 'attachment; filename="ai_analysis_database_export.xlsx"'
    }
    
    return StreamingResponse(
        stream, 
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 
        headers=headers
    )