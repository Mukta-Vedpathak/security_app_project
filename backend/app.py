from flask import Flask, request, jsonify
from googleapiclient.discovery import build
from google.oauth2 import service_account
from flask_cors import CORS
from datetime import datetime
from twilio.rest import Client
import os

app = Flask(__name__)
CORS(app)

# Twilio credentials (it’s better to load these from environment variables)
TWILIO_SID = os.getenv("TWILIO_SID", "AC05a85e2c43442877e98039e227a5f8f4")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "2ae69be51d821f93d5e532a7e5beae00")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "+12294719484")

client = Client(TWILIO_SID, TWILIO_AUTH_TOKEN)


# Google Sheets API setup
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = 'credentials.json'

STUDENT_SHEET_ID = '1emmPzBdJrkWNIllVhRFc2ptqid9-GZySkaVMeVQBFgo' 
WARDEN_SHEET_ID='1K-4kB8au_aDDHhdUAtjqZ5gKbiw8LZwadsniaEfu4tQ'

credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)
service = build('sheets', 'v4', credentials=credentials)

# Temporary storage for fetched student details
fetched_students = {}

# Route to fetch student details from the existing Google Sheet
@app.route('/fetch_student', methods=['POST'])
def fetch_student():
    try:
        student_id = request.json.get('StudentId')
        result = service.spreadsheets().values().get(
            spreadsheetId=STUDENT_SHEET_ID, range="Sheet1!A2:V").execute()
        rows = result.get('values', [])
        for row in rows:
            if row[0] == student_id:
                student_details = {
                    "StudentId": row[0],
                    "FaceId": row[1],
                    "Name": row[2],
                    "MobileNumber": row[3],
                    "Gender": row[5],
                    "HostelName": row[6],
                    "RoomNo": row[7],
                    "Batch": row[8],
                    "Course": row[9],
                    "NEET_JEE": row[10]
                }
                fetched_students[student_id] = student_details
                return jsonify(student_details)
        return jsonify({"error": "Student not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    

@app.route('/fetch_student_requests', methods=['POST'])
def fetch_student_requests():
    try:
        # Parse incoming request
        data = request.get_json()
        print("Incoming request data:", data)

        student_id = str(data.get('StudentId')).strip()
        if not student_id:
            print("Missing StudentId in request")
            return jsonify({"error": "StudentId is required"}), 400

        # Fetch rows from Google Sheet
        result = service.spreadsheets().values().get(
            spreadsheetId=WARDEN_SHEET_ID, range="Sheet1!A2:V").execute()
        rows = result.get('values', [])
        print("Rows fetched from Google Sheet:", rows)

        # Define default values for optional columns
        default_values = {
            "OutDate": "PENDING",
            "InDate": "PENDING",
            "Reason": "No reason provided",
            "Warden_OutApproval": "PENDING",
            "Warden_InApproval": "PENDING",
        }

        # Filter rows for the specific student
        student_requests = []
        for index, row in enumerate(rows):
            print(f"Processing row {index}: {row}")

            if len(row) < 12:  # Minimum number of columns to consider
                print(f"Row {index} has insufficient columns (found {len(row)}): {row}")
                continue

            row_student_id = str(row[0]).strip()
            print(f"Row {index}: StudentId = {row_student_id}, Match = {row_student_id == student_id}")

            if row_student_id == student_id:
                student_requests.append({
                    "RequestId": index + 1,
                    "OutDate": row[11] if len(row) > 11 else default_values["OutDate"],
                    "InDate": row[17] if len(row) > 17 else default_values["InDate"],
                    "Reason": row[10] if len(row) > 10 else default_values["Reason"],
                    "Warden_OutApproval": row[13] if len(row) > 13 else default_values["Warden_OutApproval"],
                    "Warden_InApproval": row[18] if len(row) > 18 else default_values["Warden_InApproval"],
                })

        print("Filtered student requests:", student_requests)
        if not student_requests:
            print(f"No requests found for StudentId: {student_id}")
            return jsonify({"message": "No requests found for the given StudentId"}), 404

        return jsonify(student_requests), 200

    except KeyError as ke:
        print("KeyError:", ke)
        return jsonify({"error": f"KeyError: {ke}"}), 400

    except IndexError as ie:
        print("IndexError:", ie)
        return jsonify({"error": f"IndexError: {ie}"}), 400

    except Exception as e:
        print("Unexpected Error:", e)
        return jsonify({"error": str(e)}), 500


@app.route('/submit_out_request', methods=['POST'])
def submit_out_request():
    try:
        data = request.json
        print("Incoming data:", data)  # Debugging payload

        # Extract nested fields
        student_details = data.get('studentDetails', {})
        leave_request = data.get('leaveRequest', {})

        student_id = student_details.get('StudentId')
        reason = leave_request.get('reason')
        out_date = leave_request.get('outDate')

        # Validate required fields
        if not all([student_id, reason, out_date]):
            print("Missing fields:", {"StudentId": student_id, "Reason": reason, "OutDate": out_date})  # Debugging missing fields
            return jsonify({"error": "All fields (StudentId, Reason, OutDate) are required"}), 400

        # Fetch existing rows to check for duplicates
        result = service.spreadsheets().values().get(
            spreadsheetId=WARDEN_SHEET_ID, range="Sheet1!A2:M").execute()
        rows = result.get('values', [])

        # Check for duplicate StudentId + OutDate
        for row in rows:
            if row[0] == student_id and row[10] == out_date:  # Columns A (StudentId) and K (OutDate)
                return jsonify({"error": "Request with the same StudentId and OutDate already exists"}), 409

        # Prepare and append data
        outing_request = [
            student_details.get('StudentId'),
            student_details.get('FaceId'),
            student_details.get('Name'),
            student_details.get('MobileNumber'),
            student_details.get('Gender'),
            student_details.get('HostelName'),
            student_details.get('RoomNo'),
            student_details.get('Batch'),
            student_details.get('Course'),
            student_details.get('NEET_JEE'),
            reason,
            out_date,
            "OUT"
        ]

        # Append data to the Google Sheet
        service.spreadsheets().values().append(
            spreadsheetId=WARDEN_SHEET_ID,
            range="Sheet1!A:M",
            valueInputOption="USER_ENTERED",
            body={"values": [outing_request]}
        ).execute()

        print("Outing request submitted:", outing_request)  # Debugging appended data
        return jsonify({"message": "Outing request submitted successfully"}), 201
    except Exception as e:
        print("Error:", e)  # Debugging unexpected exceptions
        return jsonify({"error": str(e)}), 500

@app.route('/submit_in_request', methods=['POST'])
def submit_in_request():
    try:
        data = request.json
        print("Incoming data:", data)  # Debugging payload

        # Extract nested fields
        student_details = data.get('studentDetails', {})
        leave_request = data.get('leaveRequest', {})

        student_id = student_details.get('StudentId')
        in_date = leave_request.get('inDate')

        # Validate required fields
        if not all([student_id, in_date]):
            print("Missing fields:", {"StudentId": student_id, "InDate": in_date})  # Debugging missing fields
            return jsonify({"error": "StudentId and InDate are required"}), 400

        # Fetch existing rows to check for matching StudentId and non-empty OutDate
        result = service.spreadsheets().values().get(
            spreadsheetId=WARDEN_SHEET_ID, range="Sheet1!A2:R").execute()
        rows = result.get('values', [])

        # Identify the row to update
        for idx, row in enumerate(rows):
            # Ensure row has enough columns and check for matching StudentId and existing OutDate
            if len(row) > 11 and row[0] == student_id and row[11] and row[12] == "OUT":  # Columns A (StudentId) and L (OutDate)
                # Update InDate in column 12 (L) of the matched row
                row_number = idx + 2  # Adding 2 to account for header and zero-based index
                update_range = f"Sheet1!R{row_number}"
                service.spreadsheets().values().update(
                    spreadsheetId=WARDEN_SHEET_ID,
                    range=update_range,
                    valueInputOption="USER_ENTERED",
                    body={"values": [[in_date]]}
                ).execute()

                 # Update Status in column 13 (M) to "IN"
                status_range = f"Sheet1!M{row_number}"
                service.spreadsheets().values().update(
                    spreadsheetId=WARDEN_SHEET_ID,
                    range=status_range,
                    valueInputOption="USER_ENTERED",
                    body={"values": [["IN"]]}
                ).execute()

                print(f"InDate updated for StudentId {student_id} in row {row_number}")
                return jsonify({"message": "InDate updated successfully"}), 200

        # If no matching row is found
        print(f"No matching entry found for StudentId {student_id} with an OutDate.")
        return jsonify({"error": "No existing entry found with the given StudentId and OutDate"}), 404
    except Exception as e:
        print("Error:", e)  # Debugging unexpected exceptions
        return jsonify({"error": str(e)}), 500

@app.route('/warden/login', methods=['POST'])
def warden_login():
    data = request.get_json()
    app.logger.info(f"Received data: {data}")  # Log the received data
    username = data.get('username')
    password = data.get('password')
    
    if username == "123" and password == "123":
        return jsonify({"message": "Login successful"}), 200
    else:
        return jsonify({"message": "Unauthorized"}), 401

@app.route('/warden/out_request_dashboard', methods=['GET'])
def fetch_warden_out_dashboard():
    try:
        current_date = datetime.today().date()  # Get today's date
        print(f"Current date: {current_date}")  # Debugging current date
        
        # Fetch all rows from the warden's Google Sheet
        result = service.spreadsheets().values().get(
            spreadsheetId=WARDEN_SHEET_ID, range="Sheet1!A2:V").execute()
        rows = result.get('values', [])

        # Format the response, handling missing columns gracefully
        requests = []
        for row in rows:
            try:
                # Check if the row has sufficient columns
                if len(row) >= 12:  # Ensure that there are at least 12 columns
                    date_str = row[11]  # OutDate is expected at index 11 (OUT-DATE)
                    try:
                        out_date = datetime.strptime(date_str, "%d-%m-%Y").date()
                        print(f"Parsing OutDate for {row[2]}: {out_date}")  # Debugging OutDate
                    except ValueError as e:
                        print(f"Error parsing OutDate for {row[2]}: {date_str} -> {e}")
                        continue  # Skip rows with invalid date format

                    print(f"Comparing current date {current_date} with OutDate {out_date}")  # Debugging the comparison
                    
                    if current_date <= out_date and row[12].upper() == "OUT":
                        print(f"Checking Status for {row[2]}: {row[12]}")  # Debugging Status
                        
                        # Check if Warden Out Approval (row[13]) is empty or contains only whitespace
                        warden_out_approval = row[13].strip() if len(row) > 13 else ""
                        print(f"Checking Warden Approval for {row[2]}: '{warden_out_approval}'")  # Debugging Warden Approval
                        
                        # Only add to the requests if Warden Out Approval is empty or contains only spaces
                        if warden_out_approval == "":
                            # Make sure row has all the required fields, otherwise set them to empty
                            request = {
                                "StudentId": row[0] if len(row) > 0 else "",
                                "FaceId": row[1] if len(row) > 1 else "",
                                "Name": row[2] if len(row) > 2 else "",
                                "MobileNumber": row[3] if len(row) > 3 else "",
                                "Gender": row[4] if len(row) > 4 else "",
                                "HostelName": row[5] if len(row) > 5 else "",
                                "RoomNo": row[6] if len(row) > 6 else "",
                                "Batch": row[7] if len(row) > 7 else "",
                                "Course": row[8] if len(row) > 8 else "",
                                "NEET_JEE": row[9] if len(row) > 9 else "",
                                "Reason": row[10] if len(row) > 10 else "",
                                "OutDate": row[11] if len(row) > 11 else "",
                                "Status": row[12] if len(row) > 12 else "",
                                "Warden_OutApproval": warden_out_approval,
                                "WardenNameOut": row[14] if len(row) > 14 else "",
                                "WardenRemarksOut": row[15] if len(row) > 15 else "",
                                "OutTime": row[16] if len(row) > 16 else "",
                                "InDate": row[17] if len(row) > 17 else "",
                                "Warden_InApproval": row[18] if len(row) > 18 else "",
                                "WardenNameIn": row[19] if len(row) > 19 else "",
                                "WardenRemarksIn": row[20] if len(row) > 20 else "",
                                "InTime": row[21] if len(row) > 21 else ""
                            }
                            requests.append(request)
                        else:
                            print(f"Skipping row due to Warden Out Approval filled for {row[2]}")
            except Exception as e:
                # Log the error for the problematic row
                print(f"Error processing row {row}: {e}")

        return jsonify(requests), 200
    except Exception as e:
        # Log the error for the entire request
        print(f"Error fetching warden dashboard: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/warden/in_request_dashboard', methods=['GET'])
def fetch_warden_in_dashboard():
    try:
        current_date = datetime.today().date()  # Get today's date
        print(f"Current date: {current_date}")  # Debugging current date

        # Fetch all rows from the warden's Google Sheet
        result = service.spreadsheets().values().get(
            spreadsheetId=WARDEN_SHEET_ID, range="Sheet1!A2:V").execute()
        rows = result.get('values', [])

        # Format the response, handling missing columns gracefully
        requests = []
        for row in rows:
            try:
                # Check if the row has sufficient columns
                if len(row) >= 18:  # Ensure that there are at least 18 columns
                    date_str = row[17]  # InDate is expected at index 17
                    try:
                        in_date = datetime.strptime(date_str, "%d-%m-%Y").date()
                    except ValueError:
                        print(f"Invalid InDate format for {row[2]}: {date_str}")
                        continue  # Skip rows with invalid date format

                    if current_date <= in_date and row[12].upper() == "IN":
                        warden_out_approval = row[13].strip() if len(row) > 13 else ""
                        warden_in_approval = row[18].strip() if len(row) > 18 else ""

                        # Only add to the requests if Warden In Approval is empty
                        if not warden_in_approval:
                            request = {
                                "StudentId": row[0] if len(row) > 0 else "",
                                "FaceId": row[1] if len(row) > 1 else "",
                                "Name": row[2] if len(row) > 2 else "",
                                "MobileNumber": row[3] if len(row) > 3 else "",
                                "Gender": row[4] if len(row) > 4 else "",
                                "HostelName": row[5] if len(row) > 5 else "",
                                "RoomNo": row[6] if len(row) > 6 else "",
                                "Batch": row[7] if len(row) > 7 else "",
                                "Course": row[8] if len(row) > 8 else "",
                                "NEET_JEE": row[9] if len(row) > 9 else "",
                                "Reason": row[10] if len(row) > 10 else "",
                                "OutDate": row[11] if len(row) > 11 else "",
                                "Status": row[12] if len(row) > 12 else "",
                                "Warden_OutApproval": warden_out_approval,
                                "WardenNameOut": row[14] if len(row) > 14 else "",
                                "WardenRemarksOut": row[15] if len(row) > 15 else "",
                                "OutTime": row[16] if len(row) > 16 else "",
                                "InDate": row[17] if len(row) > 17 else "",
                                "Warden_InApproval": row[18] if len(row) > 18 else "",
                                "WardenNameIn": row[19] if len(row) > 19 else "",
                                "WardenRemarksIn": row[20] if len(row) > 20 else "",
                                "InTime": row[21] if len(row) > 21 else ""
                            }
                            requests.append(request)
            except Exception as e:
                print(f"Error processing row {row}: {e}")

        return jsonify(requests), 200
    except Exception as e:
        print(f"Error fetching warden dashboard: {e}")
        return jsonify({"error": "Failed to fetch requests, please try again later."}), 500


@app.route('/warden/update_out_status', methods=['POST'])
def update_warden_out_status():
    try:
        data = request.json
        print("Received data:", data)  # Debugging incoming data

        student_id = data.get('StudentId')
        out_date = data.get('OutDate')  # New unique field
        approval_status = data.get('ApprovalStatus')  # Either "APPROVED" or "NOT APPROVED"
        warden_name = data.get('WardenName')  # New field for Warden's name
        remarks = data.get('Remarks')  # New field for Remarks

        # Validate required fields
        if not all([student_id, out_date, approval_status, warden_name]):
            print("Missing fields:", {
                "StudentId": student_id,
                "OutDate": out_date,
                "ApprovalStatus": approval_status,
                "WardenName": warden_name,
            })  # Debugging missing fields
            return jsonify({"error": "StudentId, OutDate, ApprovalStatus, WardenName are required"}), 400

        # Fetch existing rows from the sheet
        result = service.spreadsheets().values().get(
            spreadsheetId=WARDEN_SHEET_ID, range="Sheet1!A2:V").execute()
        rows = result.get('values', [])
        print("Fetched rows:", rows)  # Debugging fetched rows

        # Find the row to update where both StudentId and OutDate match
        row_found = False
        for idx, row in enumerate(rows):
            if len(row) > 12 and row[0] == student_id and row[11] == out_date and row[12]=="OUT":  # Match StudentId (A) and OutDate (K)
                range_to_update_status = f"Sheet1!N{idx + 2}"  # Column N for Warden Out approval 
                range_to_update_warden = f"Sheet1!O{idx + 2}"  # Column O for WardenName
                range_to_update_remarks = f"Sheet1!P{idx + 2}"  # Column P for Remarks
                print(f"Updating row {idx + 2}: {range_to_update_status} with status {approval_status}")  # Debugging update action

                # Update the approval status
                service.spreadsheets().values().update(
                    spreadsheetId=WARDEN_SHEET_ID,
                    range=range_to_update_status,
                    valueInputOption="RAW",
                    body={"values": [[approval_status]]}
                ).execute()

                # Update Warden's Name
                service.spreadsheets().values().update(
                    spreadsheetId=WARDEN_SHEET_ID,
                    range=range_to_update_warden,
                    valueInputOption="RAW",
                    body={"values": [[warden_name]]}
                ).execute()

                # Update Remarks
                service.spreadsheets().values().update(
                    spreadsheetId=WARDEN_SHEET_ID,
                    range=range_to_update_remarks,
                    valueInputOption="RAW",
                    body={"values": [[remarks]]}
                ).execute()

                row_found = True
                break  # Stop once the correct row is updated

        if row_found:
            student_mobile = "+91" + row[3]  # Assuming the mobile number is in column D
            print(f"Found mobile number for student {student_id}: {student_mobile}")  # Debugging mobile number
            print(f"Sending SMS to {student_mobile} about status: {approval_status}")  # Debugging SMS send

            try:
                # Send SMS using Twilio
                message = client.messages.create(
                    body=f"Your ward's request has been {approval_status} by Warden {warden_name}. Remarks: {remarks}",
                    from_=TWILIO_PHONE_NUMBER,
                    to=student_mobile
                )
                print(f"SMS sent successfully with SID: {message.sid}")  # Debugging successful SMS send
            except Exception as sms_error:
                print(f"Error sending SMS: {sms_error}")  # Debugging Twilio error
                return jsonify({"error": "Failed to send SMS"}), 500

            return jsonify({"message": "Status updated successfully"}), 200
        else:
            print("Request not found for student:", student_id)  # Debugging missing request
            return jsonify({"error": "Matching request not found"}), 404
    except Exception as e:
        print("Error:", e)  # Debugging unexpected exceptions
        return jsonify({"error": str(e)}), 500

@app.route('/warden/update_in_status', methods=['POST'])
def update_warden_in_status():
    try:
        data = request.json
        print("Received data:", data)  # Debugging incoming data

        student_id = data.get('StudentId')
        in_date = data.get('InDate')  # New unique field
        approval_status = data.get('ApprovalStatus')  # Either "APPROVED" or "NOT APPROVED"
        warden_name = data.get('WardenName')  # New field for Warden's name
        remarks = data.get('Remarks')  # New field for Remarks

        # Validate required fields
        if not all([student_id, in_date, approval_status, warden_name]):
            print("Missing fields:", {
                "StudentId": student_id,
                "InDate": in_date,
                "ApprovalStatus": approval_status,
                "WardenName": warden_name,
            })  # Debugging missing fields
            return jsonify({"error": "StudentId, InDate, ApprovalStatus, WardenName are required"}), 400

        # Fetch existing rows from the sheet
        result = service.spreadsheets().values().get(
            spreadsheetId=WARDEN_SHEET_ID, range="Sheet1!A2:V").execute()
        rows = result.get('values', [])
        print("Fetched rows:", rows)  # Debugging fetched rows

        # Find the row to update where both StudentId and OutDate match
        row_found = False
        for idx, row in enumerate(rows):
            if len(row) > 12 and row[0] == student_id and row[17] == in_date and row[12]=="IN":  # Match StudentId (A) and OutDate (K)
                range_to_update_status = f"Sheet1!S{idx + 2}"  # Column N for Warden Out approval 
                range_to_update_warden = f"Sheet1!T{idx + 2}"  # Column O for WardenName
                range_to_update_remarks = f"Sheet1!U{idx + 2}"  # Column P for Remarks
                print(f"Updating row {idx + 2}: {range_to_update_status} with status {approval_status}")  # Debugging update action

                # Update the approval status
                service.spreadsheets().values().update(
                    spreadsheetId=WARDEN_SHEET_ID,
                    range=range_to_update_status,
                    valueInputOption="RAW",
                    body={"values": [[approval_status]]}
                ).execute()

                # Update Warden's Name
                service.spreadsheets().values().update(
                    spreadsheetId=WARDEN_SHEET_ID,
                    range=range_to_update_warden,
                    valueInputOption="RAW",
                    body={"values": [[warden_name]]}
                ).execute()

                # Update Remarks
                service.spreadsheets().values().update(
                    spreadsheetId=WARDEN_SHEET_ID,
                    range=range_to_update_remarks,
                    valueInputOption="RAW",
                    body={"values": [[remarks]]}
                ).execute()

                row_found = True
                break  # Stop once the correct row is updated

        if row_found:
            student_mobile = "+91" + row[3]  # Assuming the mobile number is in column D
            print(f"Found mobile number for student {student_id}: {student_mobile}")  # Debugging mobile number
            print(f"Sending SMS to {student_mobile} about status: {approval_status}")  # Debugging SMS send

            try:
                # Send SMS using Twilio
                message = client.messages.create(
                    body=f"Your ward's request has been {approval_status} by Warden {warden_name}. Remarks: {remarks}",
                    from_=TWILIO_PHONE_NUMBER,
                    to=student_mobile
                )
                print(f"SMS sent successfully with SID: {message.sid}")  # Debugging successful SMS send
            except Exception as sms_error:
                print(f"Error sending SMS: {sms_error}")  # Debugging Twilio error
                return jsonify({"error": "Failed to send SMS"}), 500

            return jsonify({"message": "Status updated successfully"}), 200
        else:
            print("Request not found for student:", student_id)  # Debugging missing request
            return jsonify({"error": "Matching request not found"}), 404
    except Exception as e:
        print("Error:", e)  # Debugging unexpected exceptions
        return jsonify({"error": str(e)}), 500

    
# Guard login
@app.route('/guard/login', methods=['POST'])
def guard_login():
    data = request.json
    pin = data.get('pin')
    if pin == "123":
        return jsonify({"message": "Login successful"}), 200
    else:
        return jsonify({"error": "Invalid PIN"}), 401


# Guard dashboard: fetch final approvals
@app.route('/guard/out_dashboard', methods=['GET'])
def guard_out_dashboard():
    try:
        print("Guard Dashboard API called.")
        print("Fetching data from spreadsheet...")
        
        result = service.spreadsheets().values().get(
            spreadsheetId=WARDEN_SHEET_ID, range="Sheet1!A2:V").execute()
        rows = result.get('values', [])
        print(f"Total rows fetched: {len(rows)}")  # Debugging: Total rows fetched
        print("Raw rows fetched:", rows)  # Debugging: Inspect raw rows

        print("Filtering rows based on approval status...")
        filtered_rows = []
        for row in rows:
            if len(row) >= 14 and row[12]=="OUT" and row[13]:  # Ensure sufficient columns
                approval_status = row[13].strip().upper()
                print(f"Approval status: {approval_status}")  # Debugging: Check each status
                if approval_status in ["APPROVED", "REJECTED"]:
                    filtered_rows.append(row)
        print(f"Filtered rows count: {len(filtered_rows)}")  # Debugging: Filtered rows count
        print("Rows passing filter condition:", filtered_rows)  # Debugging: Rows passing condition

        # Format the response
        print("Formatting the response...")
        requests = []
        for row in filtered_rows:
            requests.append({
                "StudentId": row[0],
                "FaceId": row[1],
                "Name": row[2],
                "MobileNumber": row[3],
                "Gender": row[4],
                "HostelName": row[5],
                "RoomNo": row[6],
                "Batch": row[7],
                "Course": row[8],
                "NEET_JEE": row[9],
                "Reason": row[10],
                "OutDate": row[11],
                "Status": row[12],
                "Warden_OutApproval": row[13],
                "WardenNameOut": row[14] if len(row) > 14 else "",
                "WardenRemarksOut": row[15] if len(row) > 15 else "",
                "OutTime": row[16] if len(row) > 16 else "",
                "InDate": row[17] if len(row) > 17 else "",
                "Warden_InApproval": row[18] if len(row) > 18 else "",
                "WardenNameIn": row[19] if len(row) > 19 else "",
                "WardenRemarksIn": row[20] if len(row) > 20 else "",
                "InTime": row[21] if len(row) > 21 else "",
            })
        print("Response formatting complete.")  # Debugging: Confirm response formatting
        return jsonify(requests), 200
    except Exception as e:
        print(f"Error occurred: {str(e)}")  # Debugging: Log errors
        return jsonify({"error": str(e)}), 500

@app.route('/guard/in_dashboard', methods=['GET'])
def guard_in_dashboard():
    try:
        print("Guard Dashboard API called.")
        print("Fetching data from spreadsheet...")
        
        result = service.spreadsheets().values().get(
            spreadsheetId=WARDEN_SHEET_ID, range="Sheet1!A2:V").execute()
        rows = result.get('values', [])
        print(f"Total rows fetched: {len(rows)}")  # Debugging: Total rows fetched
        print("Raw rows fetched:", rows)  # Debugging: Inspect raw rows

        print("Filtering rows based on approval status...")
        filtered_rows = []
        for row in rows:
            if len(row) >= 19 and row[12]=="IN" and row[18]:  # Ensure sufficient columns
                approval_status = row[18].strip().upper()
                print(f"Approval status: {approval_status}")  # Debugging: Check each status
                if approval_status in ["APPROVED", "REJECTED"]:
                    filtered_rows.append(row)
        print(f"Filtered rows count: {len(filtered_rows)}")  # Debugging: Filtered rows count
        print("Rows passing filter condition:", filtered_rows)  # Debugging: Rows passing condition

        # Format the response
        print("Formatting the response...")
        requests = []
        for row in filtered_rows:
            requests.append({
                "StudentId": row[0],
                "FaceId": row[1],
                "Name": row[2],
                "MobileNumber": row[3],
                "Gender": row[4],
                "HostelName": row[5],
                "RoomNo": row[6],
                "Batch": row[7],
                "Course": row[8],
                "NEET_JEE": row[9],
                "Reason": row[10],
                "OutDate": row[11],
                "Status": row[12],
                "Warden_OutApproval": row[13],
                "WardenNameOut": row[14] if len(row) > 14 else "",
                "WardenRemarksOut": row[15] if len(row) > 15 else "",
                "OutTime": row[16] if len(row) > 16 else "",
                "InDate": row[17] if len(row) > 17 else "",
                "Warden_InApproval": row[18] if len(row) > 18 else "",
                "WardenNameIn": row[19] if len(row) > 19 else "",
                "WardenRemarksIn": row[20] if len(row) > 20 else "",
                "InTime": row[21] if len(row) > 21 else "",
            })
        print("Response formatting complete.")  # Debugging: Confirm response formatting
        return jsonify(requests), 200
    except Exception as e:
        print(f"Error occurred: {str(e)}")  # Debugging: Log errors
        return jsonify({"error": str(e)}), 500

# Guard search for specific student
@app.route('/guard/search', methods=['POST'])
def guard_search():
    try:
        student_id = request.json.get('StudentId')
        result = service.spreadsheets().values().get(
            spreadsheetId=WARDEN_SHEET_ID, range="Sheet1!A2:V").execute()
        rows = result.get('values', [])

        # Search for the student
        for row in rows:
            if row[0] == student_id and len(row) > 14 and row[14].strip() in ["APPROVED", "NOT APPROVED"]:
                return jsonify({
                "StudentId": row[0],
                "FaceId": row[1],
                "Name": row[2],
                "MobileNumber": row[3],
                "Gender": row[4],
                "HostelName": row[5],
                "RoomNo": row[6],
                "Batch": row[7],
                "Course": row[8],
                "NEET_JEE": row[9],
                "Reason": row[10],
                "OutDate": row[11],
                "Status": row[12],
                "Warden_OutApproval": row[13],
                "WardenNameOut": row[14] if len(row) > 14 else "",
                "WardenRemarksOut": row[15] if len(row) > 15 else "",
                "OutTime": row[16] if len(row) > 16 else "",
                "InDate": row[17] if len(row) > 17 else "",
                "Warden_InApproval": row[18] if len(row) > 18 else "",
                "WardenNameIn": row[19] if len(row) > 19 else "",
                "WardenRemarksIn": row[20] if len(row) > 20 else "",
                "InTime": row[21] if len(row) > 21 else "",
                }), 200

        return jsonify({"error": "Student not found or request not approved"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/guard/update_out_status', methods=['POST'])
def update_out_status():
    try:
        # Get JSON data from the request
        data = request.get_json()
        print("Received data for OUT status:", data)

        student_id = data.get('StudentId')
        status = data.get('Status')
        current_time = data.get('Time')  # Time when button was pressed
        print(f"Student ID: {student_id}, Status: {status}, Time: {current_time}")

        # Fetch rows from the sheet
        result = service.spreadsheets().values().get(
            spreadsheetId=WARDEN_SHEET_ID, range="Sheet1!A2:V").execute()
        rows = result.get('values', [])
        print("Fetched rows from sheet:", rows)

        # Find the row for the given student and update
        for row in rows:
            if row[0] == student_id:
                print("Found student row:", row)

                # Ensure there are enough columns (17 columns for OUT time at index 16)
                while len(row) <= 16:
                    row.append('')

                row[12] = status  # Update STATUS column
                if status == 'OUT':
                    row[16] = current_time  # Record OUT TIME
                    print(f"Updated OUT time for student {student_id} at {current_time}")
                break
        else:
            print(f"Student ID {student_id} not found in the sheet.")

        # Write the updated rows back to the sheet
        service.spreadsheets().values().update(
            spreadsheetId=WARDEN_SHEET_ID,
            range="Sheet1!A2:V",
            valueInputOption="RAW",
            body={"values": rows},
        ).execute()
        print("Updated rows written back to sheet.")

        return jsonify({"message": "Status updated successfully"}), 200

    except Exception as e:
        print("Error occurred while updating OUT status:", e)
        return jsonify({"error": str(e)}), 500

@app.route('/guard/update_in_status', methods=['POST'])
def update_in_status():
    try:
        # Get JSON data from the request
        data = request.get_json()
        print("Received data for IN status:", data)

        student_id = data.get('StudentId')
        status = data.get('Status')
        current_time = data.get('Time')  # Time when button was pressed
        print(f"Student ID: {student_id}, Status: {status}, Time: {current_time}")

        # Fetch rows from the sheet
        result = service.spreadsheets().values().get(
            spreadsheetId=WARDEN_SHEET_ID, range="Sheet1!A2:V").execute()
        rows = result.get('values', [])
        print("Fetched rows from sheet:", rows)

        # Find the row for the given student and update
        for row in rows:
            if row[0] == student_id:
                print("Found student row:", row)
                
                # Ensure there are enough columns (21 columns for IN time)
                while len(row) <= 21:  # Add empty columns until the row has 22 columns
                    row.append('')

                row[12] = status  # Update STATUS column
                if status == 'IN':
                    row[21] = current_time  # Record IN TIME
                    print(f"Updated IN time for student {student_id} at {current_time}")
                break
        else:
            print(f"Student ID {student_id} not found in the sheet.")

        # Write the updated rows back to the sheet
        service.spreadsheets().values().update(
            spreadsheetId=WARDEN_SHEET_ID,
            range="Sheet1!A2:V",
            valueInputOption="RAW",
            body={"values": rows},
        ).execute()
        print("Updated rows written back to sheet.")

        return jsonify({"message": "Status updated successfully"}), 200

    except Exception as e:
        print("Error occurred while updating IN status:", e)
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True)