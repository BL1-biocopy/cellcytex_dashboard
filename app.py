import os
import json
import tempfile
from flask import Flask, render_template, request, jsonify, session
from werkzeug.utils import secure_filename
import pandas as pd
from pathlib import Path
import shutil
import atexit

# Import the CytenaProcessor from parser.py (in the same directory)
from parser import CytenaProcessor

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-in-production'

# Create a temporary directory for uploads that will be cleaned up
TEMP_BASE_DIR = tempfile.mkdtemp(prefix='cytena_uploads_')
app.config['UPLOAD_FOLDER'] = TEMP_BASE_DIR
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max file size

# Store processed data in memory (in production, use Redis or database)
processed_data = {}

# Cleanup function to remove temp directory on exit
def cleanup_temp_dir():
    """Clean up temporary directory on application exit"""
    if os.path.exists(TEMP_BASE_DIR):
        shutil.rmtree(TEMP_BASE_DIR, ignore_errors=True)
        print(f"Cleaned up temporary directory: {TEMP_BASE_DIR}")

# Register cleanup function
atexit.register(cleanup_temp_dir)

def allowed_file(filename):
    """Check if file has allowed extension"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ['csv', 'xlsx', 'xls']

@app.route('/')
def index():
    """Render the main dashboard page"""
    return render_template('index.html')

@app.route('/download/<filename>')
def download_file(filename):
    """Serve downloadable files"""
    try:
        from flask import send_file
        file_path = os.path.join('./downloadable_data/', filename)
        
        if not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404
        
        return send_file(file_path, as_attachment=True, download_name=filename)
    except Exception as e:
        return jsonify({'error': f'Error downloading file: {str(e)}'}), 500

@app.route('/upload', methods=['POST'])
def upload_files():
    """Handle file upload and process data"""
    try:
        if 'files[]' not in request.files:
            return jsonify({'error': 'No files provided'}), 400
        
        files = request.files.getlist('files[]')
        
        if not files or files[0].filename == '':
            return jsonify({'error': 'No files selected'}), 400
        
        # Create unique session directory
        session_id = os.urandom(16).hex()
        session_dir = os.path.join(app.config['UPLOAD_FOLDER'], session_id)
        os.makedirs(session_dir, exist_ok=True)
        
        # Save uploaded files
        uploaded_files = []
        for file in files:
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(session_dir, filename)
                file.save(filepath)
                uploaded_files.append(filename)
        
        if not uploaded_files:
            shutil.rmtree(session_dir, ignore_errors=True)
            return jsonify({'error': 'No valid files uploaded'}), 400
        
        # Process the data using CytenaProcessor
        processor = CytenaProcessor()
        try:
            results_agg, results = processor.process(session_dir)
            
            # Store processed data
            processed_data[session_id] = results_agg
            
            # Get available options for dropdowns
            available_channels = results_agg['channel'].unique().tolist()
            
            # Get attribute columns (exclude metadata columns)
            possible_attributes = {
                "total_intensity": "AU",
                "average_mean_intensity": "AU",
                "relative_spheroid_area": "%",
                "total_spheroid_area": "mm2",
                "relative_fluorescence_area": "%",
                "confluency": "%",
                "total_area": "mm2",
                "object_count": "1/mm2",
                "object_count_per_fov": "per FOV"
            }
            
            available_attributes = list(set([col.split('_avg')[0].split('_std',-1)[0] for col in results_agg.columns 
                                   if col.split('_avg')[0].split('_std',-1)[0] in possible_attributes.keys()]))
            print(results_agg.columns)

            # Get well groups
            well_groups = []
            if 'Well Group' in results_agg.columns:
                well_groups = sorted(results_agg['Well Group'].dropna().unique().tolist(), 
                                   key=lambda x: str(x))
            
            # Get scan ID
            scan_id = results_agg['Scan ID'].iloc[0] if 'Scan ID' in results_agg.columns else 'Unknown'
            
            return jsonify({
                'success': True,
                'session_id': session_id,
                'channels': available_channels,
                'attributes': available_attributes,
                'well_groups': well_groups,
                'uploaded_files': uploaded_files,
                'scan_id': scan_id
            })
            
        except Exception as e:
            shutil.rmtree(session_dir, ignore_errors=True)
            return jsonify({'error': f'Processing error: {str(e)}'}), 500
        
    except Exception as e:
        return jsonify({'error': f'Upload error: {str(e)}'}), 500

@app.route('/get_plot_data', methods=['POST'])
def get_plot_data():
    """Get data for plotting based on user selections"""
    try:
        data = request.json
        session_id = data.get('session_id')
        attribute = data.get('attribute')
        channel = data.get('channel')
        well_groups = data.get('well_groups', [])
        
        if not session_id or session_id not in processed_data:
            return jsonify({'error': 'Invalid session or data not found'}), 400
        
        df = processed_data[session_id]
        
        # Filter by channel
        if channel:
            df_filtered = df[df['channel'] == channel].copy()
        else:
            df_filtered = df.copy()
        
        # Check if attribute exists
        #remove _avg and _std suffixes from df_filtered columns for checking
        df_filtered_columns_stripped = [col.replace('_avg', '').replace('_std', '') if isinstance(col, str) else col for col in df_filtered.columns]
        
        if attribute not in df_filtered_columns_stripped:
            return jsonify({'error': f'Attribute {attribute} not found in data'}), 400
        
        # Adjust attribute name to include suffixes if present in columns
        if f"{attribute}_avg" in df_filtered.columns:
            attribute = f"{attribute}_avg"
            print(f"Using attribute column: {attribute}")
        
        # Get all well groups that have data for this channel/attribute combination
        all_well_groups_with_data = []
        if 'Well Group' in df_filtered.columns:
            # Get well groups that have non-null data for this attribute
            temp_df = df_filtered.dropna(subset=['Time', attribute])
            all_well_groups_with_data = temp_df['Well Group'].dropna().unique().tolist()
        
        # Now filter by selected well groups
        if well_groups and 'Well Group' in df_filtered.columns:
            df_filtered = df_filtered[df_filtered['Well Group'].isin(well_groups)]
        
        # Prepare data for Chart.js
        # Group by Well Group and Time
        datasets = []
        
        if 'Well Group' in df_filtered.columns:
            for well_group in df_filtered['Well Group'].dropna().unique():
                group_data = df_filtered[df_filtered['Well Group'] == well_group]
                # Sort by Time and get values
                group_data = group_data.sort_values('Time')
                
                # Remove NaN values
                group_data = group_data.dropna(subset=['Time', attribute])
                
                if len(group_data) > 0:
                    datasets.append({
                        'label': str(well_group),
                        'data': [
                            {'x': float(row['Time']), 'y': float(row[attribute])}
                            for _, row in group_data.iterrows()
                            if pd.notna(row['Time']) and pd.notna(row[attribute])
                        ]
                    })
        else:
            # No Well Group column, plot all data
            df_filtered = df_filtered.sort_values('Time')
            df_filtered = df_filtered.dropna(subset=['Time', attribute])
            
            if len(df_filtered) > 0:
                datasets.append({
                    'label': 'All Data',
                    'data': [
                        {'x': float(row['Time']), 'y': float(row[attribute])}
                        for _, row in df_filtered.iterrows()
                        if pd.notna(row['Time']) and pd.notna(row[attribute])
                    ]
                })
        
        # Get the unit for the attribute
        possible_attributes = {
            "total_intensity": "AU",
            "average_mean_intensity": "AU",
            "relative_spheroid_area": "%",
            "total_spheroid_area": "mm2",
            "relative_fluorescence_area": "%",
            "confluency": "%",
            "total_area": "mm2",
            "object_count": "1/mm2",
            "object_count_per_fov": "per FOV"
        }
        
        # Remove _avg or _std suffix to get the base attribute name
        base_attribute = attribute.replace('_avg', '').replace('_std', '')
        unit = possible_attributes.get(base_attribute, '')
        
        return jsonify({
            'success': True,
            'datasets': datasets,
            'attribute': attribute,
            'channel': channel,
            'unit': unit,
            'well_groups_with_data': all_well_groups_with_data  # Send which wells have data
        })
        
    except Exception as e:
        return jsonify({'error': f'Error getting plot data: {str(e)}'}), 500

@app.route('/clear_session', methods=['POST'])
def clear_session():
    """Clear session data and remove temporary files"""
    try:
        data = request.json
        session_id = data.get('session_id')
        
        if session_id:
            # Remove processed data
            if session_id in processed_data:
                del processed_data[session_id]
            
            # Remove session's temporary files
            session_dir = os.path.join(app.config['UPLOAD_FOLDER'], session_id)
            if os.path.exists(session_dir):
                shutil.rmtree(session_dir, ignore_errors=True)
                print(f"Cleaned up session directory: {session_dir}")
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)