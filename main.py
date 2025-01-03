from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import fitz
import pandas as pd
import os
from transformers import pipeline
import uvicorn

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.post("/upload/")
async def upload_file(file: UploadFile = File(...)):
    # Save uploaded PDF temporarily
    pdf_path = f"temp_{file.filename}"
    with open(pdf_path, "wb") as pdf_file:
        pdf_file.write(await file.read())
    
    # Extract text from PDF
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    
    # Initialize the free model
    extractor = pipeline("text2text-generation", 
                        model="facebook/bart-large-cnn")
    
    # Extract company and customer info
    info_prompt = f"Extract utility company name and customer name from: {text[:1000]}"
    basic_info = extractor(info_prompt, 
                          max_length=100, 
                          min_length=30, 
                          do_sample=False)[0]['generated_text']
    
    # Extract monthly data
    monthly_prompt = f"Extract monthly consumption and cost for the last 12 months from: {text}"
    monthly_data = extractor(monthly_prompt, 
                            max_length=500, 
                            min_length=100, 
                            do_sample=False)[0]['generated_text']
    
    try:
        # Parse the extracted data
        company_name = basic_info.split('Company:')[1].split('\n')[0].strip()
        customer_name = basic_info.split('Customer:')[1].split('\n')[0].strip()
        
        # Create monthly data structure
        months_data = []
        lines = monthly_data.split('\n')
        total_consumption = 0
        total_cost = 0
        
        for line in lines:
            if 'Month:' in line:
                month_info = line.split(',')
                month_data = {
                    'Month': month_info[0].split(':')[1].strip(),
                    'Consumption': float(month_info[1].split(':')[1].strip()),
                    'Cost': float(month_info[2].split(':')[1].strip().replace('$', ''))
                }
                months_data.append(month_data)
                total_consumption += month_data['Consumption']
                total_cost += month_data['Cost']
        
        # Create Excel file
        df = pd.DataFrame(months_data)
        
        # Create Excel writer object
        excel_path = "utility_data.xlsx"
        writer = pd.ExcelWriter(excel_path, engine='xlsxwriter')
        
        # Write basic info
        info_df = pd.DataFrame({
            'Utility Company': [company_name],
            'Customer Name': [customer_name]
        })
        info_df.to_excel(writer, sheet_name='Utility Data', index=False)
        
        # Write monthly data
        df.to_excel(writer, sheet_name='Utility Data', startrow=3, index=False)
        
        # Write totals
        totals_df = pd.DataFrame({
            'Total Consumption': [total_consumption],
            'Total Cost': [f'${total_cost:.2f}']
        })
        totals_df.to_excel(writer, sheet_name='Utility Data', 
                          startrow=len(months_data)+5, index=False)
        
        # Save and close
        writer.close()
        
        # Clean up
        os.remove(pdf_path)
        
        return FileResponse(excel_path, filename="utility_data.xlsx")
        
    except Exception as e:
        raise HTTPException(status_code=500, 
                          detail=f"Error processing PDF: {str(e)}")

@app.get("/")
async def read_root():
    return FileResponse("static/index.html")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
