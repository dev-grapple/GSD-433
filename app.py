from datetime import datetime

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Omni Source Formatter")
st.title("Omni Source CSV Formatter")

OUTPUT_FILENAME = "omni_source_upload.csv"


# -----------------------
# Helpers
# -----------------------
def parse_date_value(val):
    if pd.isna(val):
        return pd.NaT
    s = str(val).strip()
    fmts = ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d", "%d.%m.%Y")
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
    try:
        dt = pd.to_datetime(s, dayfirst=True, errors="coerce")
        if pd.isna(dt):
            return pd.NaT
        return dt.date()
    except Exception:
        return pd.NaT


def to_numeric_value(x):
    if pd.isna(x) or str(x).strip() == "":
        return pd.NA
    s = str(x).replace(",", "").replace(" ", "")
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except Exception:
        try:
            return float(pd.to_numeric(s, errors="coerce"))
        except Exception:
            return pd.NA


# -----------------------
# New format pipeline (08.12.25)
# -----------------------
REQUIRED_OUTPUT_ORDER = [
    "Debtor Reference",
    "Transaction Type",
    "Document Number",
    "Document Date",
    "Document Balance",
]

CUST_ID_COL_CANDIDATES = ["customer_id"]
TRANS_NO_COL_CANDIDATES = ["transaction_number"]
DATE_COL_CANDIDATES = ["date"]
BALANCE_COL_CANDIDATES = ["balance"]


def _pick_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    cols = list(df.columns)
    lower_map = {c.lower().strip(): c for c in cols}
    for cand in candidates:
        key = cand.lower().strip()
        if key in lower_map:
            return lower_map[key]
    for c in cols:
        low = c.lower().replace(" ", "")
        for cand in candidates:
            if cand.lower().replace(" ", "") in low:
                return c
    return None


def _format_date_series(s: pd.Series) -> pd.Series:
    parsed = s.apply(parse_date_value)
    return parsed.apply(lambda d: d.strftime("%d/%m/%Y") if pd.notna(d) else "")


def process_dataframe(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    debug = {}

    cust_id_col = _pick_column(df, CUST_ID_COL_CANDIDATES)
    doc_no_col = _pick_column(df, TRANS_NO_COL_CANDIDATES)
    doc_date_col = _pick_column(df, DATE_COL_CANDIDATES)
    balance_col = _pick_column(df, BALANCE_COL_CANDIDATES)

    debug["detected_columns"] = {
        "customer_id → Debtor Reference": cust_id_col,
        "transaction_number → Document Number": doc_no_col,
        "date → Document Date": doc_date_col,
        "balance → Document Balance": balance_col,
    }

    missing = [k for k, v in debug["detected_columns"].items() if v is None]
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")

    out = pd.DataFrame()

    # Numeric balance
    balance = df[balance_col].apply(to_numeric_value).astype("Float64")

    ## Column A - Debtor Reference: Last 6-digits of customer_id
    out["Debtor Reference"] = (
        df[cust_id_col].astype(str).str.extract(r"(\d{6})$", expand=False).fillna("")
    )
    ## Column B - Transaction Type: INV if balance > 0 else CRD
    out["Transaction Type"] = balance.apply(
        lambda v: "INV" if pd.notna(v) and v > 0 else "CRD"
    )
    ## Column C - Document Number
    out["Document Number"] = df[doc_no_col].astype(str).str.strip()
    ## Column D - Document Date: format as DD/MM/YYYY
    out["Document Date"] = _format_date_series(df[doc_date_col])
    ## Column E - Document Balance: rounded to 2 decimal places
    out["Document Balance"] = balance.round(2)

    # --- Remove rows with 0 balance ---
    nonzero_mask = balance.fillna(0) != 0
    removed = len(balance) - nonzero_mask.sum()

    out = out.loc[nonzero_mask].reset_index(drop=True)
    debug["rows_removed_balance_0"] = int(removed)

    return out[REQUIRED_OUTPUT_ORDER], debug


def get_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, float_format="%.2f").encode("utf-8")


# -----------------------
# UI
# -----------------------
uploaded_file = st.file_uploader(
    "Upload the Excel or CSV file (first row = header):", type=["csv", "xlsx", "xls"]
)

if uploaded_file:
    try:
        if uploaded_file.name.lower().endswith(".csv"):
            df_in = pd.read_csv(uploaded_file, header=0)
        else:
            df_in = pd.read_excel(uploaded_file, header=0, sheet_name=0)

        if df_in.empty:
            st.error("Uploaded file is empty.")
        else:
            st.subheader("Input preview")
            st.dataframe(df_in.head(8))

            processed_df, debug = process_dataframe(df_in)
            st.subheader("Processed preview")
            st.dataframe(
                processed_df.head(8),
                column_config={
                    "Document Balance": st.column_config.NumberColumn(
                        "Document Balance", format="%.2f"
                    )
                },
            )

            with st.expander("Details"):
                st.json(debug)

            csv_bytes = get_csv_bytes(processed_df)
            st.download_button(
                label="Download processed CSV",
                data=csv_bytes,
                file_name=OUTPUT_FILENAME,
                mime="text/csv",
            )

    except Exception as e:
        st.error(f"Error: {e}")
else:
    st.info("Please upload a CSV or Excel file to begin.")
