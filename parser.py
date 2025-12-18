import pandas as pd
import os
import json
import openpyxl
import string
from pathlib import Path
import re
from metadata_parser import MetadataParser

class CytenaProcessor:
    
    def _validate_directory(self, data_dir: str) -> Path:
        """
        Validate that data directory exists and contains expected files.
        
        Args:
            data_dir: Path to data directory
            
        Returns:
            Path object for the validated directory
            
        Raises:
            FileNotFoundError: If directory doesn't exist
            ValueError: If no supported files found
        """
        dir_path = Path(data_dir)
        if not dir_path.exists():
            raise FileNotFoundError(f"Data directory not found: {data_dir}")
        
        supported_file_extensions=['.csv', '.xlsx', '.json']

        # Check for supported files
        found_files = []
        for ext in supported_file_extensions:
            found_files.extend(list(dir_path.glob(f'*{ext}')))
        
        if not found_files:
            raise ValueError(
                f"No supported files found in {data_dir}. "
                f"Expected extensions: {supported_file_extensions}"
            )
        
        return dir_path
    
    def _well_to_label(self,well):
        row_letter = string.ascii_uppercase[well["Row"]]   # 0 → A, 1 → B, ...
        col_number = well["Column"] + 1                    # 0 → 1, 1 → 2, ...
        return f"{row_letter}{col_number}"

    def _parse_json_metadata(self, json_path: str) -> dict:
        """
        Parse JSON metadata file to extract well group information.
        Args:
            json_path: Path to directory containing AnalysisWellGroup.json (exported from CELLCYTE X instrument)
        Returns:
            dict: Mapping of well group names to lists of well labels, e.g. {"Group1": ["A1", "A2"], "Group2": ["B1", "B2"]}
        """
        with open(os.path.join(json_path, "AnalysisWellGroup.json"), 'r') as f:
            content = json.load(f)
        metadata = {group["GroupName"]: [self._well_to_label(w) for w in group["SelectedWells"]] 
                  for group in content["AnalysisWellGroupsCollection"]}
        return metadata

    def _extract_scan_id(self, data_dir):
        prefixes=set()
        for file in os.listdir(data_dir):
            if file.endswith('.csv'):
                prefix=file.split('_')[0]
                prefixes.add(prefix)
        if len(prefixes)==1:
            scan_id=prefixes.pop()
        else:
            print("Multiple scan IDs found")
            scan_id=None
        return scan_id
    
    def parse_position_summary_files(self, data_dir: str, possible_channels: dict, possible_attributes: dict):
        data_dict_raw={}
        for file in os.listdir(data_dir):
            if file.endswith('.csv') and 'summary_positions' in file:
                label=file.split('summary_positions_')[1].replace('.csv','')
                #verify that label is made of possible channel + "_" + possible attribute
                channel, attribute = label.split('_',1)
                if channel not in possible_channels.keys():
                    print(f"ERROR: Channel {channel} not recognized")
                if attribute not in possible_attributes.keys():
                    print(f"ERROR: Attribute {attribute} not recognized")
                df=pd.read_csv(os.path.join(data_dir,file))
                data_dict_raw[label]=df
        
        data_dict_processed={}
        for label, df in data_dict_raw.items():
            #drop the first column if it is named "Scan"
            if df.columns[0]=='Scan':
                df=df.drop(columns=[df.columns[0]])
            #Change column names from second column onwards to match first row
            df.columns=[df.columns[0]] + df.iloc[0,1:].tolist()
            #remove first 2 rows
            df=df.iloc[2:,:]
            #check if all column names apart from the first column name contain "Position 1" 
            if all(['Position 1' in col for col in df.columns[1:]]):
                #replace the string "Position 1 - " with an empty string in all column names apart from the first column name
                df.columns=[df.columns[0]] + [col.replace(' - Position 1','') for col in df.columns[1:]]
            else:
                return False
        return data_dict_processed
    
    def parse_well_summary_files(self, data_dir: str, possible_channels: dict, possible_attributes: dict):
        """
        Parse well summary CSV files from Cytena scan instrument.
        
        Args:
            data_dir: Directory containing csv files from the Cytena scan instrument.
        """
        data_dict_raw={}
        for file in os.listdir(data_dir):
            if file.endswith('.csv') and 'summary_wells' in file:
                label=file.split('summary_wells_')[1].replace('.csv','')
                #verify that label is made of possible channel + "_" + possible attribute
                channel, attribute = label.split('_',1)
                if channel not in possible_channels.keys():
                    print(f"ERROR: Channel {channel} not recognized")
                if attribute not in possible_attributes.keys():
                    print(f"ERROR: Attribute {attribute} not recognized")
                df=pd.read_csv(os.path.join(data_dir,file))
                data_dict_raw[label]=df
        
        data_dict_processed={}
        for label, df in data_dict_raw.items():
            #drop the first column if it is named "Scan"
            if df.columns[0]=='Scan':
                df=df.drop(columns=[df.columns[0]])
            #drop the columns named "Stdev"
            if 'Stdev' in df.columns:
                df=df.drop(columns=['Stdev'])
            #Change column names from second column onwards to match first row
            df.columns=[df.columns[0]] + df.iloc[0,1:].tolist()
            #remove first 2 rows
            df=df.iloc[2:,:]
            data_dict_processed[label]=df
        return data_dict_processed
    
    def process(self, data_dir: str):
        """
        Process 3D Spheroid Scan data.
        
        Args:
            data_dir: Directory containing csv files from the Cytena scan instrument and an Excel file with well metadata.
            
        Returns:
            ProcessingResult with processed DataFrame
        """
        data_dir = self._validate_directory(data_dir) 

        scan_id = self._extract_scan_id(data_dir)

        #define possible channels and possible measurements with units
        possible_channels={"BF":"brightfield", "green":"green", "EC":"enhanced contrast"}

        possible_attributes={"total_intensity":"AU","average_mean_intensity":"AU","relative_spheroid_area":"%",
                             "total_spheroid_area":"mm2","relative_fluorescence_area":"%", "confluency":"%",
                             "total_area":"mm2","object_count":"1/mm2","object_count_per_fov":"per FOV"}

        if not self.parse_position_summary_files(data_dir, possible_channels, possible_attributes):
            print("INFO: Multiple positions detected, switching to well summary files")
            data_dict_processed=self.parse_well_summary_files(data_dir, possible_channels, possible_attributes)
        else:
            data_dict_processed=self.parse_position_summary_files(data_dir, possible_channels, possible_attributes)

        for label, df in data_dict_processed.items():
            # replace "Well " with an empty string in all column names except the first column name
            df.columns=[df.columns[0]] + [col.replace('Well ','') for col in df.columns[1:]]
            #convert all columns to numeric, coerce errors
            df=df.apply(pd.to_numeric, errors='coerce')
            #strip all df column names
            df.columns=[col.strip() if isinstance(col, str) else col for col in df.columns]
            #append label and processed df to data_dict_processed
            data_dict_processed[label]=df.reset_index(drop=True)

        #find excel file in data_dir and print error if not found or multiple found
        excel_files=[file for file in os.listdir(data_dir) if file.endswith('.xlsx')]
        metadata_parser=MetadataParser()
        if len(excel_files)==1:
            excel_path=os.path.join(data_dir,excel_files[0])
            print("Excel file found:", excel_path)
            metadata=pd.read_excel(excel_path, engine='openpyxl')  # Test if file can be opened
            #if first column is named "Well"
            if metadata.columns[0]=='Well':
                print("Found excel metadata template")
                metadata["Well Group"]=metadata[metadata.columns[1:]].astype(str).agg(' '.join, axis=1) #make new column "Well Group" by combining all columns 
            else:
                print("Did not find excel metadata template. Trying to parse Disco Bio Excel format")
                metadata=metadata_parser.parse_disco_bio_excel(metadata)
        elif len(excel_files)>1:
            print("ERROR: Multiple Excel files found in data directory. Expects only one Excel file.")
        elif len(excel_files)==0:
            print("INFO: No Excel file found in data directory, looking for JSON file")
            json_files=[file for file in os.listdir(data_dir) if file.endswith('.json')]
            if len(json_files)>1:
                print("ERROR: Multiple JSON files found in data directory")
            elif len(json_files)==0:
                print("ERROR: No JSON file found in data directory. Metadata extraction is not possible.")
            elif len(json_files)==1:
                print("JSON file found:", json_files[0])
                json_path=os.path.join(data_dir,json_files[0])
                metadata=metadata_parser.parse_json_metadata(json_path)
        # convert all dataframes in data_dict_processed to their long format and store them in a separate dictionary called data_dict_long
        data_dict_long={}
        for label, df in data_dict_processed.items():
            df_long=pd.melt(df, id_vars=[df.columns[0]], var_name='Well', value_name=label.split('_',1)[1])
            data_dict_long[label]=df_long

        #for each df in data_dict_long, merge the df and the metadata dataframe on the column "Well"
        merged_dfs=[]
        for label, df in data_dict_long.items():
            channel=label.split('_')[0]
            df["channel"]=channel
            merged_df=pd.merge(df, metadata, on='Well', how='left')
            merged_dfs.append(merged_df)
        
        #merge all dataframes in merged_dfs that have the same value in the column "channel" on "Well" and "Time"
        merged_dfs_final=[]
        channels=possible_channels.keys()
        #define cols_to_merge as all columns in metadata and "Time" and "channel"
        cols_to_merge=[col for col in metadata.columns] + ['Time', 'channel']
        for channel in channels:
            dfs_to_merge=[df for df in merged_dfs if df['channel'].iloc[0]==channel]
            if len(dfs_to_merge)>1:
                merged_df_channel=dfs_to_merge[0]
                for df in dfs_to_merge[1:]:
                    merged_df_channel=pd.merge(merged_df_channel, df, on=cols_to_merge, how='left')
                merged_dfs_final.append(merged_df_channel)
            elif len(dfs_to_merge)==1:
                merged_dfs_final.append(dfs_to_merge[0])

        #concatenate all dataframes in merged_dfs_final into a single dataframe
        results=pd.concat(merged_dfs_final, axis=0, ignore_index=True)
        results['Scan ID']=scan_id

        #new df starting from results, aggregate by well group, time, channel and compute mean and stdev of all attribute columns
        aggregate_cols=['Well Group', 'Time', 'channel']
        attribute_cols=[col for col in results.columns if col in possible_attributes.keys()]
        results_agg=results.groupby(aggregate_cols)[attribute_cols].agg(['mean','std']).reset_index()
        #flatten multiindex columns
        results_agg.columns=['_'.join(col).strip('_') for col in results_agg.columns.values]
        #split colname by _, if last element is mean, remove it and add _avg
        results_agg.columns = results_agg.columns.str.replace(r'_mean$', '_avg', regex=True)

        results_agg['Scan ID']=scan_id

        #results["Analyzed Entity ID"]=None
        #results['Laboratory Result Type'] = 'Assay'
        #results['Measurement Type'] = '3D Spheroid Scan'
        #results['Antigen ID'] = None


        return results_agg, results