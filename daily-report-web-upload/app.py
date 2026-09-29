import csv
import hashlib
import io
from dataclasses import asdict
from datetime import date
from pathlib import Path
import streamlit as st
from report_generator import FIELDS, WorkItem, align_work_items, generate_report, parse_comma_text
from ai_service import extract_work
from web_config import get_deepseek_api_key

BASE = Path(__file__).resolve().parent
st.set_page_config(page_title="生产工作日报", page_icon="📄", layout="centered")
st.title("生产工作日报自动填表")
st.caption("原始文字 → 自动提取 → 核对编辑 → 按原模板生成 Word")
st.caption("默认值：有工作时危险作业填“否”，今日完成情况填“已完成”，备注留空；明确填写的内容优先。")
report_date = st.date_input("日报日期", value=date.today())
auto = st.checkbox("自动整理排版", value=True, help="统一段落间距；长备注移入工作描述。边框及合并修复始终启用。")

mode = st.radio("输入方式", ["原始文字（API自动整理）", "逗号文本（无需API）"])
is_ai = mode.startswith("原始")
if is_ai:
    with st.expander("AI模型设置"):
        model = st.text_input("模型名称", value="deepseek-flash")
    if not get_deepseek_api_key():
        st.info("服务器尚未配置 DeepSeek API Key，请联系管理员。无需API模式仍可使用。")
raw = st.text_area("粘贴工作内容", height=280, key="raw")
fingerprint = hashlib.sha256((mode + raw).encode()).hexdigest()
if is_ai:
    consent = st.checkbox("我同意将以上工作文字发送至 DeepSeek 进行整理（包含其中的姓名等信息）。", key="consent")
else:
    consent = True
    st.caption("字段顺序：" + ",".join(FIELDS) + "。仅英文逗号分字段；每行8个字段。")
if st.button("自动整理并预览" if is_ai else "解析并预览", type="primary"):
    for k in ("records", "download", "source", "warnings", "ai_review"):
        st.session_state.pop(k, None)
    try:
        if not consent:
            raise ValueError("请先确认是否允许发送至 DeepSeek；也可使用无需API的逗号模式。")
        review_details = []
        with st.spinner("正在整理…"):
            if is_ai:
                api_key = get_deepseek_api_key()
                if not api_key:
                    raise ValueError("服务器尚未配置 DeepSeek API Key，请联系管理员。")
                items, warnings = extract_work(raw, api_key, model, review_details=review_details)
            else:
                items, warnings = parse_comma_text(raw), []
        items = align_work_items(items)
        st.session_state.records = [dict(zip(FIELDS, asdict(item).values())) for item in items]
        st.session_state.source = fingerprint
        st.session_state.warnings = warnings
        if is_ai:
            st.session_state.ai_review = review_details
        st.session_state.revision = st.session_state.get("revision", 0) + 1
    except ValueError as exc:
        st.error(str(exc))
    except Exception:
        st.error("AI整理失败，请稍后重试。" if is_ai else "解析失败，请检查输入后重试。")

if "records" in st.session_state:
    if st.session_state.source != fingerprint:
        st.warning("原始文字或输入方式已改变，请重新整理，避免生成旧数据。")
        st.stop()
    st.subheader("核对结果（可直接修改单元格）")
    st.warning("请核对专业、设备编号、姓名、完成情况和危险作业。“否”和“已完成”可能来自默认填充，不代表已经核实。")
    for warning in st.session_state.warnings:
        st.warning(warning)
    if is_ai and "ai_review" in st.session_state:
        checks = st.session_state.ai_review
        flagged = [check for check in checks if check["needs_review"]]
        if flagged:
            st.caption("AI识别检查")
            for check in flagged:
                st.warning(f"⚠️ 建议确认 · {check['id']}：{check['review_reason'] or '请核对本事项'}")
        else:
            st.caption("AI识别检查：未发现需要人工确认的项目。")
        with st.expander("查看AI识别对照"):
            st.caption("以下为AI初次识别结果（含程序默认值），仅供对照；人工修改请使用下方表格。")
            for check in checks:
                result = check["result"]
                st.text(f"{check['id']} · {result['profession']}\n原文：\n{check['raw_text']}")
                if check["id"].startswith("T"):
                    st.text(f"识别结果：\n工作内容：{result['today']}\n人员：{result['people']}\n危险作业：{result['today_hazard']}\n完成情况：{result['status']}\n备注：{result['remark']}")
                else:
                    st.text(f"识别结果：\n明日计划：{result['tomorrow']}\n危险作业：{result['tomorrow_hazard']}")
    edited = st.data_editor(st.session_state.records, num_rows="dynamic", use_container_width=True,
                            key=f"editor_{st.session_state.revision}")
    with st.expander("逐条核对（手机上可逐项查看）"):
        for index, row in enumerate(edited, 1):
            st.text(f"{index}. {row.get('专业') or ''}\n今日工作：{row.get('今日工作') or ''}\n"
                    f"人员：{row.get('人员') or ''}\n明日计划：{row.get('明日计划') or ''}\n"
                    f"今日危险作业：{row.get('危险作业') or ''}  明日危险作业：{row.get('明日危险作业') or ''}")
    st.caption(f"当前共 {len(edited)} 条。专业按原模板排序；今日、明日各自连续编号。")
    signature = hashlib.sha256((repr(edited) + str(report_date) + str(auto)).encode()).hexdigest()
    with st.form("confirm"):
        confirmed = st.checkbox("已核对以上数据，确认生成")
        submit = st.form_submit_button("生成 Word")
    if submit:
        st.session_state.pop("download", None)
        try:
            if not confirmed:
                raise ValueError("请先核对数据并勾选确认。")
            items = []
            for row in edited:
                values = [str(row.get(k) or "").strip() for k in FIELDS]
                if not any(values):
                    continue
                if not values[0] or values[0] == "待确认":
                    raise ValueError("请填写正确专业，不能保留“待确认”。")
                if not values[1] and not values[5]:
                    raise ValueError("每行至少填写今日工作或明日计划。")
                items.append(WorkItem(*values))
            output = io.BytesIO()
            generate_report(BASE / "template/生产工作日报模板.docx", items, report_date, output, auto)
            st.session_state.download = (signature, output.getvalue(), f"{report_date:%Y.%m.%d}各专业生产工作.docx")
        except ValueError as exc:
            st.error(str(exc))
        except Exception:
            st.error("Word生成失败，请稍后重试。")
    if "download" in st.session_state and st.session_state.download[0] == signature:
        _, data, name = st.session_state.download
        st.success("生成成功。")
        st.download_button("下载 Word", data, name, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    csv_out = io.StringIO()
    writer = csv.writer(csv_out)
    writer.writerow(FIELDS)
    writer.writerows([r.get(k) or "" for k in FIELDS] for r in edited)
    st.download_button("下载整理后的逗号文本", csv_out.getvalue().encode("utf-8-sig"), "整理结果.csv", "text/csv")
