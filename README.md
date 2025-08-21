# Invoice PDF Parser Web Application

A Flask web application that allows your team to drag-and-drop PDF invoices, automatically parse FedEx invoice data, and send the extracted information directly to Airtable.

## 🚀 Features

- **Drag & Drop Interface**: Modern, intuitive file upload with drag-and-drop support
- **PDF Processing**: Automatically extracts table data from FedEx invoices using pdfplumber
- **Airtable Integration**: Sends parsed data directly to your Airtable base
- **Team-Ready**: Designed for multiple users in your department
- **Error Handling**: Comprehensive error reporting and user feedback
- **Responsive Design**: Works on desktop and mobile devices

## 📋 Prerequisites

- Airtable account with API access
- Railway account (for hosting)
- Basic familiarity with environment variables

## 🛠️ Local Development Setup

### 1. Clone or Download the Project

Save all the provided files in a project directory:

```
invoice-parser/
├── app.py
├── parser.py
├── requirements.txt
├── Procfile
├── railway.json
├── .env.example
└── templates/
    └── index.html
```

### 2. Set Up Python Environment

```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure Environment Variables

```bash
# Copy example file
cp .env.example .env

# Edit .env file with your values
```

Required environment variables:
- `AIRTABLE_API_KEY`: Your Airtable API key
- `AIRTABLE_BASE_ID`: Your Airtable base ID
- `AIRTABLE_TABLE_NAME`: Table name (default: "Invoices")
- `SECRET_KEY`: Flask secret key for sessions

### 4. Set Up Airtable

1. **Get API Key**: 
   - Go to https://airtable.com/developers/web/api/introduction
   - Create a personal access token
   - Add scopes: `data.records:read` and `data.records:write`

2. **Get Base ID**: 
   - Open your Airtable base
   - Base ID is in the URL: `https://airtable.com/[BASE_ID]/...`

3. **Prepare Table Structure**:
   Your Airtable table should have these fields:
   ```
   - numer_faktury (Single line text)
   - data_faktury (Single line text)
   - typ (Single line text)
   - AWB (Single line text)
   - data_wysylki (Single line text)
   - dlugosc (Number)
   - szerokosc (Number)
   - wysokosc (Number)
   - usluga (Long text)
   - waga_zafakturowana (Number)
   - sztuki (Number)
   - waga (Number)
   - numer_referencyjny (Single line text)
   - podlega_vat (Number)
   - bez_vat (Number)
   - lacznie (Number)
   - informacje_nadawca (Long text)
   - informacje_odbiorca (Long text)
   - odebral (Single line text)
   - czas_odebrania (Single line text)
   ```

### 5. Run Locally

```bash
python app.py
```

Visit `http://localhost:5000` to test the application.

## 🚄 Railway Deployment

Railway is the perfect hosting solution for this application because:
- **Easy Deployment**: One-click deployment from GitHub
- **Automatic Scaling**: Handles traffic spikes automatically
- **Affordable**: $5/month hobby plan with usage-based pricing
- **No Server Management**: Focus on your app, not infrastructure

### Why Railway > Make.com for This Use Case

**Railway** is ideal because:
- ✅ Hosts custom Flask applications
- ✅ Supports file uploads and processing
- ✅ Team access with custom domains
- ✅ Full control over your application logic
- ✅ Integrates with your existing Python code

**Make.com** would be overkill because:
- ❌ Designed for workflow automation, not custom apps
- ❌ Limited file processing capabilities
- ❌ No custom user interfaces
- ❌ More expensive for this specific use case
- ❌ Requires rebuilding your parsing logic

### Step-by-Step Railway Deployment

1. **Prepare Your Code**
   ```bash
   # Initialize git repository
   git init
   git add .
   git commit -m "Initial commit"

   # Push to GitHub (create repo first on GitHub)
   git remote add origin https://github.com/yourusername/invoice-parser.git
   git branch -M main
   git push -u origin main
   ```

2. **Deploy on Railway**
   - Visit [railway.com](https://railway.com)
   - Sign up/login with GitHub
   - Click "New Project"
   - Select "Deploy from GitHub repo"
   - Choose your repository
   - Railway will automatically detect Flask and deploy

3. **Set Environment Variables**
   - Go to your project dashboard
   - Click on your service
   - Go to "Variables" tab
   - Add your environment variables:
     ```
     AIRTABLE_API_KEY=your_api_key
     AIRTABLE_BASE_ID=your_base_id
     AIRTABLE_TABLE_NAME=Invoices
     SECRET_KEY=your-secret-key
     ```

4. **Get Your URL**
   - Go to "Settings" → "Networking"
   - Click "Generate Domain"
   - Your app will be available at the generated URL

### Railway Pricing

- **Free Trial**: $5 credit to get started
- **Hobby Plan**: $5/month + usage
  - 8GB RAM, 8 vCPU per service
  - Perfect for department-wide usage
- **Usage Rates**:
  - Memory: $10/GB/month
  - CPU: $20/vCPU/month
  - For a typical invoice processing app: ~$8-15/month total

## 📱 How to Use

1. **Access the Application**
   - Navigate to your Railway URL
   - You'll see a clean, modern interface

2. **Upload PDFs**
   - Drag and drop PDF files onto the upload area
   - Or click "Choose File" to browse
   - Only PDF files up to 16MB are accepted

3. **View Results**
   - Processing status is shown in real-time
   - Success/error messages with details
   - Records are automatically sent to Airtable

4. **Team Access**
   - Share the Railway URL with your department
   - Multiple users can use it simultaneously
   - Each upload is processed independently

## 🔧 Code Structure

### `app.py`
Main Flask application with:
- File upload handling
- PDF processing integration
- Airtable API communication
- Error handling and user feedback

### `parser.py`
Refactored invoice parsing logic:
- PDF table extraction using pdfplumber
- Complex FedEx invoice data parsing
- Airtable record formatting

### `templates/index.html`
Modern web interface with:
- Drag-and-drop functionality
- Real-time upload progress
- Responsive design
- Error handling

## 🐛 Troubleshooting

### Common Issues

1. **"No tables found in PDF"**
   - Ensure the PDF contains structured table data
   - Check if it's a FedEx invoice format
   - Try with a different PDF

2. **Airtable API Error**
   - Verify API key and permissions
   - Check base ID and table name
   - Ensure table has correct field structure

3. **File Upload Fails**
   - Check file size (max 16MB)
   - Ensure file is a valid PDF
   - Try with a simpler PDF first

### Debugging

Enable debug mode locally:
```bash
export FLASK_ENV=development
python app.py
```

Check Railway logs:
- Go to Railway dashboard
- Click on your service
- View "Deployments" tab for logs

## 📈 Scaling and Improvements

### For Higher Usage

1. **Upgrade Railway Plan**
   - Pro plan: 32GB RAM, 32 vCPU
   - Better for high-volume processing

2. **Add Background Processing**
   - Use Celery with Redis for large files
   - Process files asynchronously

3. **Add File Storage**
   - Store processed PDFs temporarily
   - Add download links for processed files

### Additional Features

- **User Authentication**: Add login system
- **Processing History**: Show upload history
- **Batch Processing**: Handle multiple files
- **Email Notifications**: Send results via email
- **API Endpoints**: Add REST API for integration

## 💰 Cost Comparison

### Railway (Recommended)
- **Setup**: $5/month + usage
- **Maintenance**: Minimal (automatic updates)
- **Scalability**: Automatic
- **Total Cost**: ~$10-20/month for department use

### Alternative: Make.com
- **Setup**: More complex, requires rebuilding logic
- **Cost**: $9+/month + operations pricing
- **Limitations**: No custom UI, limited file processing
- **Total Cost**: $20-50+/month

### Alternative: Self-hosting
- **Setup**: Complex server management
- **Maintenance**: High (security, updates, backups)
- **Cost**: $10-50+/month
- **Risk**: Downtime, security issues

**Recommendation**: Railway offers the best balance of cost, simplicity, and features for your use case.

## 🔐 Security Considerations

- Environment variables for sensitive data
- File size limits (16MB max)
- PDF file type validation
- Temporary file cleanup
- HTTPS enabled by default on Railway

## 📞 Support

For issues with:
- **Code**: Check error messages and logs
- **Railway**: Visit [Railway documentation](https://docs.railway.app)
- **Airtable**: Check [Airtable API docs](https://airtable.com/developers/web/api/introduction)

## 📄 License

This project is provided as-is for your internal use. Modify as needed for your requirements.
