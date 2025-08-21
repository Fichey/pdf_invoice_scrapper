#!/bin/bash
# Simple deployment helper script for Railway

echo "🚀 Invoice Parser Deployment Helper"
echo "=================================="

# Check if git is initialized
if [ ! -d ".git" ]; then
    echo "Initializing git repository..."
    git init
fi

# Check for environment variables
if [ ! -f ".env" ]; then
    echo "⚠️  Warning: No .env file found. Copy .env.example to .env and configure your variables."
    echo "Required variables:"
    echo "- AIRTABLE_API_KEY"
    echo "- AIRTABLE_BASE_ID"
    echo "- AIRTABLE_TABLE_NAME"
    echo "- SECRET_KEY"
    echo ""
fi

# Add all files
echo "Adding files to git..."
git add .

# Commit changes
echo "Committing changes..."
git commit -m "Deploy invoice parser application - $(date)"

# Check if remote exists
if ! git remote | grep -q origin; then
    echo "⚠️  No git remote found. Please add your GitHub repository:"
    echo "git remote add origin https://github.com/yourusername/invoice-parser.git"
    echo ""
    echo "Then push with:"
    echo "git branch -M main"
    echo "git push -u origin main"
else
    echo "Pushing to repository..."
    git push
    echo "✅ Code pushed to GitHub!"
    echo ""
    echo "Next steps:"
    echo "1. Go to railway.com"
    echo "2. Create new project from GitHub repo"
    echo "3. Set environment variables in Railway dashboard"
    echo "4. Generate domain and share with your team"
fi

echo ""
echo "🎉 Deployment preparation complete!"
