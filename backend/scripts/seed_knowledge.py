"""
脚本：scripts/seed_knowledge.py
作用：向 knowledge_articles 表导入基础法律条文，并同步向量化写入 Qdrant。

用法：
    python scripts/seed_knowledge.py

说明：
- 先将法条写入 PostgreSQL / SQLite；
- 然后使用 BGE-M3 模型将法条编码为向量，写入 Qdrant 的 knowledge_articles collection；
- 如果 Qdrant 未启动，仅写入 SQL 数据库，不影响主流程。
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.models.knowledge import KnowledgeArticle

settings = get_settings()
engine = create_engine(settings.SYNC_DATABASE_URL)
Session = sessionmaker(bind=engine)


ARTICLES = [
    # ---------- 劳动合同法 ----------
    {
        "law_name": "《中华人民共和国劳动合同法》",
        "article_number": "第十七条",
        "article_title": "劳动合同应当具备的条款",
        "article_text": "劳动合同应当具备以下条款：（一）用人单位的名称、住所和法定代表人或者主要负责人；（二）劳动者的姓名、住址和居民身份证或者其他有效身份证件号码；（三）劳动合同期限；（四）工作内容和工作地点；（五）工作时间和休息休假；（六）劳动报酬；（七）社会保险；（八）劳动保护、劳动条件和职业危害防护；（九）法律、法规规定应当纳入劳动合同的其他事项。",
        "category": "劳动合同法",
    },
    {
        "law_name": "《中华人民共和国劳动合同法》",
        "article_number": "第十九条",
        "article_title": "试用期",
        "article_text": "劳动合同期限三个月以上不满一年的，试用期不得超过一个月；劳动合同期限一年以上不满三年的，试用期不得超过二个月；三年以上固定期限和无固定期限的劳动合同，试用期不得超过六个月。同一用人单位与同一劳动者只能约定一次试用期。以完成一定工作任务为期限的劳动合同或者劳动合同期限不满三个月的，不得约定试用期。试用期包含在劳动合同期限内。劳动合同仅约定试用期的，试用期不成立，该期限为劳动合同期限。",
        "category": "劳动合同法",
    },
    {
        "law_name": "《中华人民共和国劳动合同法》",
        "article_number": "第二十二条",
        "article_title": "服务期",
        "article_text": "用人单位为劳动者提供专项培训费用，对其进行专业技术培训的，可以与该劳动者订立协议，约定服务期。劳动者违反服务期约定的，应当按照约定向用人单位支付违约金。违约金的数额不得超过用人单位提供的培训费用。用人单位要求劳动者支付的违约金不得超过服务期尚未履行部分所应分摊的培训费用。",
        "category": "劳动合同法",
    },
    {
        "law_name": "《中华人民共和国劳动合同法》",
        "article_number": "第三十八条",
        "article_title": "劳动者可以解除劳动合同的情形",
        "article_text": "用人单位有下列情形之一的，劳动者可以解除劳动合同：（一）未按照劳动合同约定提供劳动保护或者劳动条件的；（二）未及时足额支付劳动报酬的；（三）未依法为劳动者缴纳社会保险费的；（四）用人单位的规章制度违反法律、法规的规定，损害劳动者权益的；（五）因本法第二十六条第一款规定的情形致使劳动合同无效的；（六）法律、行政法规规定劳动者可以解除劳动合同的其他情形。",
        "category": "劳动合同法",
    },
    {
        "law_name": "《中华人民共和国劳动合同法》",
        "article_number": "第四十六条",
        "article_title": "经济补偿",
        "article_text": "有下列情形之一的，用人单位应当向劳动者支付经济补偿：（一）劳动者依照本法第三十八条规定解除劳动合同的；（二）用人单位依照本法第三十六条规定向劳动者提出解除劳动合同并与劳动者协商一致解除劳动合同的；（三）用人单位依照本法第四十条规定解除劳动合同的；（四）用人单位依照本法第四十一条第一款规定解除劳动合同的；（五）除用人单位维持或者提高劳动合同约定条件续订劳动合同，劳动者不同意续订的情形外，依照本法第四十四条第一项规定终止固定期限劳动合同的；（六）依照本法第四十四条第四项、第五项规定终止劳动合同的；（七）法律、行政法规规定的其他情形。",
        "category": "劳动合同法",
    },
    {
        "law_name": "《中华人民共和国劳动合同法》",
        "article_number": "第二十五条",
        "article_title": "违约金",
        "article_text": "除本法第二十二条和第二十三条规定的情形外，用人单位不得与劳动者约定由劳动者承担违约金。",
        "category": "劳动合同法",
    },
    {
        "law_name": "《中华人民共和国劳动合同法》",
        "article_number": "第二十六条",
        "article_title": "劳动合同无效或部分无效",
        "article_text": "下列劳动合同无效或者部分无效：（一）以欺诈、胁迫的手段或者乘人之危，使对方在违背真实意思的情况下订立或者变更劳动合同的；（二）用人单位免除自己的法定责任、排除劳动者权利的；（三）违反法律、行政法规强制性规定的。对劳动合同的无效或者部分无效有争议的，由劳动争议仲裁机构或者人民法院确认。",
        "category": "劳动合同法",
    },
    # ---------- 劳动法 / 社会保险法 ----------
    {
        "law_name": "《中华人民共和国劳动法》",
        "article_number": "第七十二条",
        "article_title": "社会保险基金来源",
        "article_text": "社会保险基金按照保险类型确定资金来源，逐步实行社会统筹。用人单位和劳动者必须依法参加社会保险，缴纳社会保险费。",
        "category": "劳动法",
    },
    {
        "law_name": "《中华人民共和国社会保险法》",
        "article_number": "第五十八条",
        "article_title": "用人单位办理社会保险登记",
        "article_text": "用人单位应当自用工之日起三十日内为其职工向社会保险经办机构申请办理社会保险登记。未办理社会保险登记的，由社会保险经办机构核定其应当缴纳的社会保险费。",
        "category": "社会保险法",
    },
    # ---------- 公司法（2024） ----------
    {
        "law_name": "《中华人民共和国公司法》",
        "article_number": "第八十六条",
        "article_title": "股权转让后的变更登记",
        "article_text": "股东转让股权的，应当书面通知公司，请求变更股东名册；需要办理变更登记的，并请求公司向公司登记机关办理变更登记。公司无正当理由不得拒绝。公司拒绝或者在合理期限内不予答复的，转让人、受让人可以依法向人民法院提起诉讼。",
        "category": "公司法",
    },
    {
        "law_name": "《中华人民共和国公司法》",
        "article_number": "第八十八条",
        "article_title": "未按期出资股权转让的责任",
        "article_text": "股东转让已认缴出资但未届出资期限的股权的，由受让人承担缴纳该出资的义务；受让人未按期足额缴纳出资的，转让人对受让人未按期缴纳的出资承担补充责任。未按照公司章程规定的出资日期缴纳出资或者作为出资的非货币财产的实际价额显著低于所认缴的出资额的股东转让股权的，转让人与受让人在出资不足的范围内承担连带责任；受让人不知道且不应当知道存在上述情形的，由转让人承担责任。",
        "category": "公司法",
    },
    # ---------- 民法典合同编（租赁、买卖、借款、技术服务通用） ----------
    {
        "law_name": "《中华人民共和国民法典》",
        "article_number": "第七百零四条",
        "article_title": "租赁合同主要内容",
        "article_text": "租赁合同的内容一般包括租赁物的名称、数量、用途、租赁期限、租金及其支付期限和方式、租赁物维修等条款。",
        "category": "租赁合同",
    },
    {
        "law_name": "《中华人民共和国民法典》",
        "article_number": "第七百零七条",
        "article_title": "租赁期限六个月以上应书面形式",
        "article_text": "租赁期限六个月以上的，应当采用书面形式。当事人未采用书面形式，无法确定租赁期限的，视为不定期租赁。",
        "category": "租赁合同",
    },
    {
        "law_name": "《中华人民共和国民法典》",
        "article_number": "第七百一十六条",
        "article_title": "承租人经出租人同意转租",
        "article_text": "承租人经出租人同意，可以将租赁物转租给第三人。承租人转租的，承租人与出租人之间的租赁合同继续有效；第三人造成租赁物损失的，承租人应当赔偿损失。承租人未经出租人同意转租的，出租人可以解除合同。",
        "category": "租赁合同",
    },
    {
        "law_name": "《中华人民共和国民法典》",
        "article_number": "第五百九十五条",
        "article_title": "买卖合同定义",
        "article_text": "买卖合同是出卖人转移标的物的所有权于买受人，买受人支付价款的合同。",
        "category": "买卖合同",
    },
    {
        "law_name": "《中华人民共和国民法典》",
        "article_number": "第六百一十条",
        "article_title": "标的物质量要求",
        "article_text": "因标的物不符合质量要求，致使不能实现合同目的的，买受人可以拒绝接受标的物或者解除合同。买受人拒绝接受标的物或者解除合同的，标的物毁损、灭失的风险由出卖人承担。",
        "category": "买卖合同",
    },
    {
        "law_name": "《中华人民共和国民法典》",
        "article_number": "第六百二十六条",
        "article_title": "买受人支付价款",
        "article_text": "买受人应当按照约定的数额和支付方式支付价款。对价款的数额和支付方式没有约定或者约定不明确的，适用本法第五百一十条、第五百一十一条第二项和第五项的规定。",
        "category": "买卖合同",
    },
    {
        "law_name": "《中华人民共和国民法典》",
        "article_number": "第六百六十七条",
        "article_title": "借款合同定义",
        "article_text": "借款合同是借款人向贷款人借款，到期返还借款并支付利息的合同。",
        "category": "借款合同",
    },
    {
        "law_name": "《中华人民共和国民法典》",
        "article_number": "第六百八十条",
        "article_title": "禁止高利放贷",
        "article_text": "禁止高利放贷，借款的利率不得违反国家有关规定。借款合同对支付利息没有约定的，视为没有利息。借款合同对支付利息约定不明确，当事人不能达成补充协议的，按照当地或者当事人的交易方式、交易习惯、市场利率等因素确定利息；自然人之间借款的，视为没有利息。",
        "category": "借款合同",
    },
    {
        "law_name": "《最高人民法院关于审理民间借贷案件适用法律若干问题的规定》",
        "article_number": "第二十五条",
        "article_title": "民间借贷利率司法保护上限",
        "article_text": "出借人请求借款人按照合同约定利率支付利息的，人民法院应予支持，但是双方约定的利率超过合同成立时一年期贷款市场报价利率四倍的除外。",
        "category": "借款合同",
    },
    {
        "law_name": "《最高人民法院关于审理民间借贷案件适用法律若干问题的规定》",
        "article_number": "第二十六条",
        "article_title": "民间借贷本金认定",
        "article_text": "借据、收据、欠条等债权凭证载明的借款金额，一般认定为本金。预先在本金中扣除利息的，人民法院应当将实际出借的金额认定为本金。",
        "category": "借款合同",
    },
    {
        "law_name": "《最高人民法院关于审理民间借贷案件适用法律若干问题的规定》",
        "article_number": "第二十九条",
        "article_title": "逾期利率、违约金与其他费用并存",
        "article_text": "出借人与借款人既约定了逾期利率，又约定了违约金或者其他费用，出借人可以选择主张逾期利息、违约金或者其他费用，也可以一并主张，但是总计超过合同成立时一年期贷款市场报价利率四倍的部分，人民法院不予支持。",
        "category": "借款合同",
    },
    {
        "law_name": "《中华人民共和国民法典》",
        "article_number": "第八百七十八条",
        "article_title": "技术咨询合同、技术服务合同定义",
        "article_text": "技术咨询合同是当事人一方以技术知识为对方就特定技术项目提供可行性论证、技术预测、专题技术调查、分析评价报告等所订立的合同。技术服务合同是当事人一方以技术知识为对方解决特定技术问题所订立的合同，不包括承揽合同和建设工程合同。",
        "category": "技术服务合同",
    },
    {
        "law_name": "《中华人民共和国民法典》",
        "article_number": "第八百八十五条",
        "article_title": "技术成果归属",
        "article_text": "技术咨询合同、技术服务合同履行过程中，受托人利用委托人提供的技术资料和工作条件完成的新的技术成果，属于受托人。委托人利用受托人的工作成果完成的新的技术成果，属于委托人。当事人另有约定的，按照其约定。",
        "category": "技术服务合同",
    },
]


def seed_sql(db) -> list[KnowledgeArticle]:
    """将法条写入 SQL 数据库，返回新插入的记录列表。"""
    inserted_records = []
    for article in ARTICLES:
        exists = (
            db.query(KnowledgeArticle)
            .filter(
                KnowledgeArticle.law_name == article["law_name"],
                KnowledgeArticle.article_number == article["article_number"],
            )
            .first()
        )
        if not exists:
            record = KnowledgeArticle(**article)
            db.add(record)
            db.flush()  # 获取自增 ID
            inserted_records.append(record)
        else:
            inserted_records.append(exists)
    return inserted_records


def seed_vector(records: list[KnowledgeArticle]) -> int:
    """将法条记录向量化并写入 Qdrant。Qdrant 不可用时返回 0 并打印警告。"""
    if not records:
        return 0

    try:
        from app.rag.vector_store import get_vector_store

        store = get_vector_store()
        articles = [
            {
                "id": r.id,
                "law_name": r.law_name,
                "article_number": r.article_number,
                "article_title": r.article_title or "",
                "article_text": r.article_text,
                "category": r.category,
            }
            for r in records
        ]
        return store.upsert_knowledge(articles)
    except Exception as e:
        print(f"[WARN] 向量库写入失败（Qdrant 可能未启动）: {e}")
        return 0


def main():
    db = Session()
    try:
        records = seed_sql(db)
        db.commit()
        print(f"成功导入 {len(records)} 条法律条文到 SQL 数据库。")

        vector_count = seed_vector(records)
        if vector_count > 0:
            print(f"成功向量化写入 {vector_count} 条法律条文到 Qdrant。")
    except Exception as e:
        print(f"导入失败: {e}")
        db.rollback()
        raise
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    main()
