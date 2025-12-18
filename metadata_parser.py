import pandas as pd
import os
import json
import openpyxl
import string
from pathlib import Path
import re

class MetadataParser:
    
    def parse_json_metadata(self, json_path: str) -> dict:
        """
        Parse JSON metadata file to extract well group information.
        Args:
            json_path: Path to directory containing AnalysisWellGroup.json (exported from CELLCYTE X instrument)
        Returns:
            pd.DataFrame: DataFrame with columns "Well" and "Well Group"
        """
        with open(os.path.join(json_path, "AnalysisWellGroup.json"), 'r') as f:
            content = json.load(f)
        metadata_dict = {group["GroupName"]: [self._well_to_label(w) for w in group["SelectedWells"]] 
                  for group in content["AnalysisWellGroupsCollection"]}
        #convert metadata_dict to dataframe with columns "Well" and "Well Group"
        metadata_rows=[]
        for group, wells in metadata_dict.items():
            for well in wells:
                metadata_rows.append({"Well":well, "Well Group":group})
        metadata=pd.DataFrame(metadata_rows)
        return metadata
    
    def parse_disco_bio_excel(self, metadata:pd.DataFrame) -> dict:
        """
        Parse Disco Bio Excel metadata file to extract well group information.
        Args:
            excel_path: Path to the Disco Bio Excel file
        Returns:
            pd.DataFrame: DataFrame with columns "Well" and "Well Group"
        """
        
        #check that second column has values A-H
        unique_values=metadata.iloc[:,1].unique()
        expected_values=list(string.ascii_uppercase[:8])  # ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']
        if set(unique_values)==set(expected_values):
            print("Metadata second column is valid")
            #rename second column to "well column"
            metadata.rename(columns={metadata.columns[1]: "well column"}, inplace=True)
        else:
            print("Metadata second column is invalid")

        #check that all column names apart from the first two columns contain numbers 1-12
        for col in metadata.columns[2:]:
            try:
                num=int(col)
                if num<1 or num>12:
                    print(f"Invalid column name: {col}")
            except ValueError:
                print(f"Invalid column name: {col}")
        #if only first row of a column is filled, propagate that value to the entire column
        for col in metadata.columns:
            if metadata[col].notna().sum()==1:
                value=metadata[col].dropna().values[0]
                metadata[col]=value
        
        #remove " (PPB-###)" from metadata entries
        for col in metadata.columns[2:]:
            #ignore non-string columns
            if metadata[col].dtype == object:
                metadata[col]=metadata[col].str.replace(r' \(PPB-\d+\)', '', regex=True)
        
        #check that first column is named ['Ab conc.\n[nM]'] and contains numeric values
        if metadata.columns[0]!='Ab conc.\n[nM]':
            print("First column name is invalid, expected 'Ab conc.\\n[nM]'")
        if not pd.to_numeric(metadata['Ab conc.\n[nM]'], errors='coerce').notna().all():
            print("First column contains non-numeric values")
        
        #convert 'Ab conc.\n[nM]' column to numeric
        metadata['Ab conc.\n[nM]']=pd.to_numeric(metadata['Ab conc.\n[nM]'], errors='coerce')
        #keep only 2 significant figures
        metadata['Ab conc.\n[nM]']=metadata['Ab conc.\n[nM]'].round(2)

        #iterate through rows of df and append the entry in Ab conc.[nM] to entries in columns named 1-8
        for index, row in metadata.iterrows():
            ab_conc=row['Ab conc.\n[nM]']
            for col in metadata.columns[2:]:
                if str(col).isdigit() and 1 <= int(col) <= 8:
                    if pd.notna(row[col]):
                        metadata.at[index, col]=f"{row[col]} ({ab_conc} nM)"
        metadata.drop(columns=['Ab conc.\n[nM]'], inplace=True)

        metadata = metadata.rename(columns={"well column": "Row"})

        # Melt the dataframe
        long_df = (
            metadata.melt(id_vars="Row", var_name="Col", value_name="Well Group")
        )

        # Build the combined well name (e.g. A1)
        long_df["Well"] = long_df["Row"] + long_df["Col"].astype(str)

        # Reorder columns
        long_df = long_df[["Well", "Well Group"]]

        return long_df