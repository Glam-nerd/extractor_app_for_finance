import io
import os
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import pandas as pd
import streamlit as st

# Load environment variables from .env file if present
load_dotenv()


def get_gdrive_credentials():
  # 1. Try loading from Streamlit Cloud secrets first
  try:
    if "gcp_service_account" in st.secrets:
      credentials_dict = dict(st.secrets["gcp_service_account"])
      return service_account.Credentials.from_service_account_info(
          credentials_dict, scopes=["https://www.googleapis.com/auth/drive"]
      )
  except Exception:
    pass

  # 2. Fall back to local .env file / environment variable path
  credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
  if credentials_path and os.path.exists(credentials_path):
    return service_account.Credentials.from_service_account_file(
        credentials_path, scopes=["https://www.googleapis.com/auth/drive"]
    )

  raise FileNotFoundError(
      "Google Service Account credentials not found. Please configure"
      " st.secrets on Streamlit Cloud or your local .env file."
  )


st.set_page_config(
    page_title="Sametro Data Extractor & Mapper", page_icon="📊", layout="wide"
)

st.title("Sametro Field Converter")
st.write(
    "My custom app for converting finance data into standard analytics format"
)
st.divider()

# Initialize session state for tracking upload counts
if "upload_count" not in st.session_state:
  st.session_state.upload_count = 1
  st.session_state.last_file_name = None

# Sidebar Configuration
with st.sidebar:
  st.header("⚙️ Configuration")
  uploaded_file = st.file_uploader(
      "Upload your data file (CSV or Excel)", type=["csv", "xlsx", "xls"]
  )

  # Detect new file uploads to increment the counter automatically
  if (
      uploaded_file is not None
      and uploaded_file.name != st.session_state.last_file_name
  ):
    st.session_state.upload_count += 1
    st.session_state.last_file_name = uploaded_file.name
    # Update default text box value dynamically with the incremented count
    base_name, ext = os.path.splitext(uploaded_file.name)
    st.session_state["gdrive_filename_input"] = (
        f"raw_{base_name}_{st.session_state.upload_count}{ext}"
    )

  # Google Drive settings with dynamic counter default
  default_filename = (
      f"raw_uploaded_finance_data_{st.session_state.upload_count}.csv"
  )
  gdrive_file_name = st.text_input(
      "Raw File Name in Drive",
      value=st.session_state.get("gdrive_filename_input", default_filename),
      key="gdrive_filename_input",
  )

  gdrive_enabled = st.checkbox("Enable Google Drive Backup")
  gdrive_folder_id = st.text_input(
      "Google Drive Folder ID (Optional)",
      value="",
      help="Leave blank to save in the Service Account's root directory.",
  )

# --- MAIN AREA LOGIC ---
if uploaded_file is not None:
  try:
    # Load raw file with header=None to properly target row 0 and 1
    if uploaded_file.name.endswith(".csv"):
      df = pd.read_csv(uploaded_file, header=None)
    else:
      df = pd.read_excel(uploaded_file, header=None)

    # --- YOUR CUSTOM PREPROCESSING LOGIC ---
    all_data = []
    i = 0
    while i < df.shape[1]:
      officer_cell = df.iloc[0, i]

      if pd.notna(officer_cell) and str(officer_cell).strip() != "":
        officer_name = str(officer_cell).strip()

        if i + 2 < df.shape[1]:
          block = df.iloc[1:, [i, i + 1, i + 2]].copy()
          block.columns = ["Date", "Repayment Amount", "Recovery Amount"]
          block["Officer name"] = officer_name
          all_data.append(block)

        i += 3
      else:
        i += 1

    if all_data:
      result_df = pd.concat(all_data, ignore_index=True)
      result_df = result_df[
          result_df["Date"].notna()
          & (result_df["Date"].astype(str).str.upper() != "TOTAL")
          & (result_df["Date"].astype(str).str.upper() != "OFFICER NAME")
      ]

      result_df["Repayment Amount"] = pd.to_numeric(
          result_df["Repayment Amount"], errors="coerce"
      ).fillna(0)
      result_df["Recovery Amount"] = pd.to_numeric(
          result_df["Recovery Amount"], errors="coerce"
      ).fillna(0)

      result_df["Total Collection"] = (
          result_df["Repayment Amount"] + result_df["Recovery Amount"]
      )
      result_df = result_df[[
          "Date",
          "Officer name",
          "Repayment Amount",
          "Recovery Amount",
          "Total Collection",
      ]]
      result_df = result_df.reset_index(drop=True)

      st.success(
          f"Successfully preprocessed **{uploaded_file.name}**!"
          f" ({len(result_df)} rows parsed)"
      )

      # Preview the cleaned data table
      st.subheader("🔍 Cleaned Data Preview")
      st.dataframe(result_df.head(15), use_container_width=True)

      # Provide a button to download the cleaned Excel file directly
      output = io.BytesIO()
      result_df.to_excel(output, index=False)
      output.seek(0)

      st.download_button(
          label="📥 Download Cleaned Excel File",
          data=output,
          file_name="cleaned_collection_report.xlsx",
          mime=(
              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          ),
      )

    else:
      st.error(
          "Could not detect any officer names in the header row. Please check"
          " your file format."
      )

    # Handle Google Drive Backup if enabled
    if gdrive_enabled:
      with st.spinner("Backing up raw file to Google Drive..."):
        creds = get_gdrive_credentials()
        service = build("drive", "v3", credentials=creds)

        mimetype = (
            "text/csv"
            if uploaded_file.name.endswith(".csv")
            else (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        )
        uploaded_file.seek(0)
        media = MediaIoBaseUpload(
            io.BytesIO(uploaded_file.getvalue()),
            mimetype=mimetype,
            resumable=True,
        )

        file_metadata = {"name": gdrive_file_name}
        if gdrive_folder_id.strip():
          file_metadata["parents"] = [gdrive_folder_id.strip()]

        service.files().create(
            body=file_metadata, media_body=media, fields="id"
        ).execute()
        st.success(
            f"Successfully backed up raw file as **{gdrive_file_name}** to"
            " Google Drive!"
        )

  except Exception as e:
    st.error(f"Error reading or processing the file: {e}")
else:
  st.info("👈 Upload a file in the sidebar to get started.")