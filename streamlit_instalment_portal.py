# Streamlit Instalment Approval Portal
# Save this file as streamlit_instalment_portal.py
# Deploy instructions are in the chat (push to GitHub -> Streamlit Community Cloud or Render/Railway).

import streamlit as st
import pandas as pd
import datetime
import io
import os
from sqlalchemy import create_engine, Column, Integer, Float, String, Boolean, DateTime, MetaData, Table
from sqlalchemy.exc import SQLAlchemyError

# ---------- Configuration ----------
# By default this app uses a local SQLite DB file `approved_customers.db`.
# For production, set env var DATABASE_URL to a Postgres URL (e.g. postgres://user:pass@host:port/dbname)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///approved_customers.db")

# Approval threshold and default minimum wage (PKR)
DEFAULT_MIN_WAGE = 37000
PASS_THRESHOLD = 60

# ---------- Database setup ----------
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
metadata = MetaData()

approved_table = Table(
    'approved_customers', metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('name', String, nullable=False),
    Column('net_salary', Float, nullable=False),
    Column('previous_defaults', Boolean, default=False),
    Column('loans_before', Integer, default=0),
    Column('loan_amount', Float, default=0.0),
    Column('payslip_signed', Boolean, default=False),
    Column('dependants', Integer, default=0),
    Column('guarantor_female', Boolean, default=False),
    Column('guarantor_male', Boolean, default=False),
    Column('score', Integer),
    Column('passes', Boolean),
    Column('approved_on', DateTime)
)

# create table if not exists
try:
    metadata.create_all(engine)
except SQLAlchemyError as e:
    st.error(f"Database initialization error: {e}")

# ---------- Evaluation function (same logic as prototype) ----------

def evaluate_candidate(data, min_wage=DEFAULT_MIN_WAGE):
    reasons = []
    score = 0

    # 1) Net salary check (30 points)
    if data['net_salary'] >= min_wage:
        score += 30
        reasons.append(f"Salary >= min wage ({min_wage}): +30")
    else:
        ratio = max(0, data['net_salary'] / (min_wage if min_wage>0 else 1))
        bonus = int(30 * ratio)
        score += bonus
        reasons.append(f"Salary below min wage: +{bonus} (proportional)")

    # 2) Previous defaults (negative impact) up to -30 points
    if data['previous_defaults']:
        score -= 30
        reasons.append("Previous defaults: -30")
    else:
        score += 10
        reasons.append("No previous defaults: +10")

    # 3) Loans taken before (int) - more loans reduces score (max -10)
    loans = max(0, int(data['loans_before']))
    loan_penalty = min(10, loans * 2)
    score -= loan_penalty
    reasons.append(f"Previous loans penalty: -{loan_penalty}")

    # 4) Loan amount relative to salary (max -15)
    if data['net_salary']>0:
        ratio = data['loan_amount'] / data['net_salary']
        if ratio <= 0.5:
            score += 10
            reasons.append("Loan amount <=50% of salary: +10")
        elif ratio <= 1.0:
            score += 5
            reasons.append("Loan amount 50-100% of salary: +5")
        else:
            penalty = min(15, int((ratio-1.0)*15))
            score -= penalty
            reasons.append(f"Loan amount > salary: -{penalty}")
    else:
        reasons.append("Net salary 0 or invalid for loan-ratio check")

    # 5) Payslip signed (yes -> +10)
    if data['payslip_signed']:
        score += 10
        reasons.append("Payslip signed: +10")
    else:
        reasons.append("Payslip not signed: +0")

    # 6) Dependants (fewer dependants -> slight bonus). Up to +5
    deps = max(0, int(data['dependants']))
    dep_bonus = max(0, 5 - deps)
    score += dep_bonus
    reasons.append(f"Dependants bonus: +{dep_bonus}")

    # 7) Guarantors: need one female AND one male for full credit (+15)
    if data['guarantor_female'] and data['guarantor_male']:
        score += 15
        reasons.append("Both guarantors present: +15")
    else:
        reasons.append("Guarantors missing or incomplete: +0")

    score = max(0, min(100, int(score)))
    passes = score >= PASS_THRESHOLD
    return score, passes, reasons

# ---------- Helper DB functions ----------

def insert_approved(row):
    ins = approved_table.insert().values(**row)
    with engine.begin() as conn:
        conn.execute(ins)


def query_approved():
    sel = approved_table.select().order_by(approved_table.c.approved_on.desc())
    with engine.connect() as conn:
        df = pd.read_sql(sel, conn)
    return df

# ---------- Streamlit UI ----------

st.set_page_config(page_title="Instalment Approval Portal", layout="wide")
st.title("Instalment Approval Portal — Wavetec")

col1, col2 = st.columns([2,1])

with col2:
    st.info("Anyone with the app link can access this page. To restrict access, deploy behind auth or add an auth mechanism.")
    st.write("#")
    min_wage = st.number_input("Minimum Wage (PKR)", value=DEFAULT_MIN_WAGE, min_value=0)
    st.write(f"Approval threshold (score) = {PASS_THRESHOLD}")

with col1:
    st.header("Evaluate a single candidate")
    with st.form("single_form"):
        name = st.text_input("Name")
        net_salary = st.number_input("Net Salary (PKR)", min_value=0.0, value=0.0)
        previous_defaults = st.checkbox("Previous Defaults", value=False)
        loans_before = st.number_input("Loans Taken Before", min_value=0, value=0)
        loan_amount = st.number_input("Loan Amount (PKR)", min_value=0.0, value=0.0)
        payslip_signed = st.checkbox("Payslip Signed", value=False)
        dependants = st.number_input("Number of Dependants", min_value=0, value=0)
        guarantor_female = st.checkbox("Female Guarantor Present", value=False)
        guarantor_male = st.checkbox("Male Guarantor Present", value=False)

        submitted = st.form_submit_button("Evaluate")

    if submitted:
        candidate = {
            'name': name.strip(),
            'net_salary': float(net_salary),
            'previous_defaults': bool(previous_defaults),
            'loans_before': int(loans_before),
            'loan_amount': float(loan_amount),
            'payslip_signed': bool(payslip_signed),
            'dependants': int(dependants),
            'guarantor_female': bool(guarantor_female),
            'guarantor_male': bool(guarantor_male)
        }
        score, passes, reasons = evaluate_candidate(candidate, min_wage=min_wage)
        st.metric(label="Score (0-100)", value=f"{score}", delta=None)
        if passes:
            st.success(f"PASS — Candidate meets the approval threshold (score {score})")
        else:
            st.error(f"FAIL — Candidate does not meet the approval threshold (score {score})")

        with st.expander("Scoring details"):
            for r in reasons:
                st.write("-", r)

        if passes:
            if st.button("Approve & Add to Database"):
                row = candidate.copy()
                row['score'] = score
                row['passes'] = True
                row['approved_on'] = datetime.datetime.utcnow()
                try:
                    insert_approved(row)
                    st.success("Candidate approved and added to DB.")
                except Exception as e:
                    st.error(f"Failed to add to DB: {e}")

# ---------- Bulk upload / evaluation ----------

st.markdown("---")
st.header("Bulk upload / evaluate")
uploaded = st.file_uploader("Upload CSV or Excel (columns: name, net_salary, previous_defaults, loans_before, loan_amount, payslip_signed, dependants, guarantor_female, guarantor_male)", type=['csv','xlsx'])

if uploaded is not None:
    try:
        if uploaded.name.lower().endswith('.csv'):
            df = pd.read_csv(uploaded)
        else:
            df = pd.read_excel(uploaded)
    except Exception as e:
        st.error(f"Failed reading file: {e}")
        df = None

    if df is not None:
        # normalize
        df_cols = {c.lower().strip(): c for c in df.columns}
        df.rename(columns={v:k for k,v in df_cols.items()}, inplace=True)

        results = []
        for _, row in df.iterrows():
            item = {
                'name': row.get('name',''),
                'net_salary': float(row.get('net_salary',0) or 0),
                'previous_defaults': bool(row.get('previous_defaults', False)),
                'loans_before': int(row.get('loans_before', 0) or 0),
                'loan_amount': float(row.get('loan_amount', 0) or 0),
                'payslip_signed': str(row.get('payslip_signed','')).strip().lower() in ['yes','true','1','y'],
                'dependants': int(row.get('dependants',0) or 0),
                'guarantor_female': str(row.get('guarantor_female','')).strip().lower() in ['yes','true','1','y'],
                'guarantor_male': str(row.get('guarantor_male','')).strip().lower() in ['yes','true','1','y']
            }
            score, passes, reasons = evaluate_candidate(item, min_wage=min_wage)
            item['score'] = score
            item['passes'] = passes
            results.append(item)

        res_df = pd.DataFrame(results)
        st.write("Bulk evaluation results")
        st.dataframe(res_df)

        if st.button("Add All PASSES to DB"):
            to_add = res_df[res_df['passes'] == True].copy()
            if to_add.empty:
                st.info("No passing candidates to add.")
            else:
                to_add['approved_on'] = datetime.datetime.utcnow()
                # insert rows
                inserted = 0
                for _, r in to_add.iterrows():
                    try:
                        insert_approved(r.to_dict())
                        inserted += 1
                    except Exception as e:
                        st.error(f"Failed to insert {r.get('name')}: {e}")
                st.success(f"Inserted {inserted} passing candidates into the DB.")

# ---------- View / Download Approved DB ----------

st.markdown("---")
st.header("Approved customers database")
try:
    df_db = query_approved()
    st.dataframe(df_db)

    csv = df_db.to_csv(index=False).encode('utf-8')
    st.download_button("Download DB as CSV", data=csv, file_name="approved_customers.csv", mime='text/csv')

except Exception as e:
    st.error(f"Could not load DB: {e}")

# ---------- Footer / notes ----------
st.markdown("---")
st.caption("Notes: This app uses an embedded evaluation model and a simple DB. For production, use a managed Postgres and enable authentication so only authorized personnel can approve customers. Contact the developer for customization.")
