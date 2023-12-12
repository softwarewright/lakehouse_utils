"""

Author: Cody Austin Davis
Date:  12/6/2023

Description: Local Model converter from Redshift / Snowflake models to Databricks

TO DO:
1. Add rule to not replace anything in between 2 sets of double brackets - DONE - Cody Davis

"""
import os
import re
import json
import argparse
from pathlib import Path
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed, wait


## Function to find all sql files within a given directory
def find_sql_files(directory:str):
    # Convert the input to a Path object
    path = Path(directory)

    # Check if the provided path is a directory
    if not path.is_dir():
        raise NotADirectoryError(f"{directory} is not a directory.")

    # List to store all .sql file paths
    sql_files = []

    # Use glob to find all .sql files recursively
    for file in path.rglob('*.sql'):
        sql_files.append(str(file))

    return sql_files


## Function to convert Snowflake/Redshift functions to dbt macros
def function_to_macro(content: str, function_name: str):

  ## Pattern to exclude replacing things inside existing curly braces / macros
  pattern = r'({}\()([^)]*)\)'.format(function_name) #Look for functions of the format name(input1,input2)
  replacement_doubleQuotes = r'{{{{lakehouse_utils.{}("\2")}}}}'.format(function_name) #Surround the expression with double curly braces, and quotes on either end
  
  ## Pattern to exclude replacing things inside existing curly braces / macros
  exclude_curlys_pattern = r'(?<!\{{\{{)\s\S*?({}\()([^)]*)\)\s\S*?(?!\}}\}})'.format(function_name)

  check_preventDoubleReplace_pattern = r'({{lakehouse_utils\.{}\()([^)]*)\)'.format(function_name)
  check_preventInnerReplace_pattern = r'(\w{}\()([^)]*)\)'.format(function_name)

  number_of_matches = len(re.findall(pattern, content, flags=re.IGNORECASE))

  ## TO DO: This assumes there is only 1 function per script - not a good assumption
  # If the function hasn't already been replaced with a macro AND isn't a subpart of another function name, then continue
  if (((re.search(check_preventDoubleReplace_pattern,content, flags=re.IGNORECASE) is None) 
      & (re.search(check_preventInnerReplace_pattern,content, flags=re.IGNORECASE) is None)) 
      | (re.search(exclude_curlys_pattern,content, flags=re.IGNORECASE) is not None)
  ):
    try:

      if (re.search(exclude_curlys_pattern,content, flags=re.IGNORECASE) is not None):
        number_of_matches = len(re.findall(exclude_curlys_pattern, content, flags=re.IGNORECASE))
      else:
        number_of_matches = len(re.findall(pattern, content, flags=re.IGNORECASE))

    except Exception as e:
      number_of_matches = 0

    if (re.search(exclude_curlys_pattern,content, flags=re.IGNORECASE) is not None):
      updated_content = re.sub(exclude_curlys_pattern, replacement_doubleQuotes, content, flags=re.IGNORECASE)
    else:
      updated_content = re.sub(pattern, replacement_doubleQuotes, content, flags=re.IGNORECASE)
    #print(updated_content)

    matched_patterns = re.findall(pattern,updated_content, flags=re.IGNORECASE) 

    #print(matched_patterns)

    for i in matched_patterns:
      
      # Substitute quotes around inner commas

      commas = r','
      quoted_commas = r'","'
      updated_match = re.sub(commas,quoted_commas,i[1], flags=re.IGNORECASE)
      updated_content = updated_content.replace(i[1], updated_match)

    # If we inadvertently surrounded a double-quoted string with more double-quotes, change these to be single quotes to prevent compatibility issues!

    double_doubleQuotes_pattern = r'""([^"]*)""'
    single_doubleQuotes_pattern = r"""'"\1"'"""
    
    updated_content = re.sub(double_doubleQuotes_pattern,single_doubleQuotes_pattern,updated_content, flags=re.IGNORECASE)

    # If we inadvertently added double-quotes to an empty input macro, remove these!

    accidental_doubleQuotes_pattern = r'({{lakehouse_utils.{}\()""\)'.format(function_name)
    fixed_noQuotes_pattern = r'\1)'
    
    updated_content = re.sub(accidental_doubleQuotes_pattern,fixed_noQuotes_pattern,updated_content, flags=re.IGNORECASE)

    ## If we have multiple instances of the same function, the quotes get strange - '" - fix this

    bad_quotes_pattern_1 = r'(\(\'\"\))'
    bad_quotes_pattern_2 = r'(\(\"\'\))'

    updated_content = re.sub(bad_quotes_pattern_1,r'()',updated_content, flags=re.IGNORECASE)
    updated_content = re.sub(bad_quotes_pattern_2,r'()',updated_content, flags=re.IGNORECASE)

  # If the previous check failed, continue unchanged
  else:
    updated_content = content
    number_of_matches = 0

  return (updated_content, number_of_matches)



## Function to convert Snowflake/Redshift functions to dbt macros
def convert_syntax_expressions(content: str, source_pattern: str, target_pattern: str):
  
  source_pattern = source_pattern
  target_pattern = target_pattern
  num_matches = 0

  #print(f"SOURCE PATTERN: {source_pattern}")
  #print(f"TARGET PATTERN: {target_pattern}")

  matched_patterns = re.findall(source_pattern, content, flags= re.DOTALL | re.IGNORECASE) 

  #print(f"MATCHED PATTERNS: {matched_patterns}")

  num_matches = len(matched_patterns)

  updated_content = re.sub(source_pattern, target_pattern, content, flags= re.DOTALL | re.IGNORECASE)
    #print(matched_patterns)

  return (updated_content, num_matches)



## Function to asynchronously kick off: open each file, loop through every function, write results
## Make new directory for new results
def process_file(full_path: str, functions_list: [str], parse_mode:str = 'functions', syntax_map : {str, str} = {}):

  ## Steps 
  ## 1. If function mode or all mode - process the function conversions first
  ## 2. If syntax or all mode - process the syntax conversions next
  ## 3. If 'all' mode - go back through to find functions after fixing syntax - this is specifically for strange thing like function calls with no parentheses like GETDATE

  converted_functions = dict()
  converted_syntax = dict()

  assert (parse_mode in ['functions', 'syntax', 'all'])

  print(f"Converting SQL File: {full_path}")

  with open(full_path, 'r+') as file:
    content = file.read()
    
    #print(f"READING CONTENT FROM {full_path}: {content}")

    ## Parse and Convert the enabled functions for the source db to databricks
    if parse_mode in ['functions', 'all']:
       
        for function_name in functions_list:
            content, no_matches = function_to_macro(content, function_name)
            #print(f"NUM MATCHES FOR: {function_name} = {no_matches}")
            converted_functions[function_name] = no_matches
    
    ## Parse and convert syntax nuances with source and target regex expressions from sourcedb/syntax_mappings.json
    if parse_mode in ['syntax', 'all']:
       
       if len(syntax_map.keys()) > 0:
          
          for key, value in syntax_map.items():
             
             #print(f"Parsing syntax mapping: {key}")
             source_pattern = value.get("source_pattern")
             target_pattern = value.get("target_pattern")

             content, num_matches = convert_syntax_expressions(content= content, source_pattern= source_pattern, target_pattern= target_pattern)

             ## Add to dicts
             converted_syntax[key] = num_matches
    
       else:
          print(f"No syntax values to parse: {syntax_map}. Skipping. ")

    ## If the syntax map changes functions that are recognized, then we need to go back through and check for functions as well
    if parse_mode == 'all':

      for function_name in functions_list:

        content, no_matches = function_to_macro(content, function_name)

        if function_name in converted_functions:
          converted_functions[function_name] += no_matches
        else: 
           converted_functions[function_name] = no_matches
           
       

    ## Instead of writing data in place, lets write it to a new model subfolder ./databricks/
    # Write content to the new file

    # Create a Path object from the full path
    original_path = Path(full_path)

    # Determine the new directory's path
    new_dir = original_path.parent.parent / (original_path.parent.name + "_to_databricks")

    # Ensure the new directory exists
    os.makedirs(new_dir, exist_ok=True)

    # Define the new file path
    new_file_path = new_dir / original_path.name

    with open(new_file_path, 'w') as file:
        file.write(content)

  return (full_path, converted_functions, converted_syntax) ## Return list of functions that converted

   

def dbt_project_functions_to_macros(base_project_path: str, input_functions: [str], subdirpath: str = '', parse_mode:str = None, syntax_map : {str, str} = {}):
  # Verify we are running in a dbt project

  ### LOCAL VERSION - 2 options - running as a parent project, or running as a package in another project. 
  ## Checks for a parent project first under the following directory assumption: /project_folder/dbt_project.yml.
  ## The package version assumes the utility helper lives under /project_folder/packages/lakehouse_utils/helper/. So it looks 3 levels up for a dbt_project file and uses that as the base directory
  try:

    dbt_file = base_project_path / 'dbt_project.yml'
    if dbt_file.is_file():
        print("Valid dbt project!")
        print("Converting .sql files in the Models folder...")
    else:
       raise(FileNotFoundError("Cannot find DBT project file. Please check the project structure and run in the correct mode (standalone vs packages.)"))

    paths = []

    sql_files = find_sql_files(f'{base_project_path}/models/{subdirpath}')

    
    # List all sql files to be checked in a folder
    ## TBD: Do not parse macros until we can dynamically handle the package/or standalone structure. We dont want to edit and parse the macros that this utility relies on
    #if parsemacro == 'true':  
    #  paths.extend(find_sql_files(f'{base_project_path}/macros'))

    print(f"SQL FILES: {sql_files}")

    with ThreadPoolExecutor() as executor:
      futures_sql = {executor.submit(process_file, p, input_functions, parse_mode, syntax_map): p for p in sql_files}
      for future in as_completed(futures_sql):
        data = future.result()
        if data:
            print(f"Processed: {data[0]} \n Converted Functions: {data[1]} \n Converted Syntax Mappings: {data[2]}")
           
        else:
            print(f"Nothing to change: {data}")
            

  except Exception as e:
      raise(e)  



def find_dbt_project_file(start_path: str, run_mode: str = "standalone"):

    """
    This local version has 2 methods of running, it can run as a standalone or as a DBT package in another existing project. 
    1. Package Version - If running as a package, it will traverse the directory and look for the dbt_project.yml file. 
    The package version assumes the utility helper lives under /project_folder/packages/lakehouse_utils/helper/. So it looks 3 levels up for a dbt_project file and uses that as the base directory

    2. Standalone Version - This is more flexible, and simply traverses up the directory from its current point until it finds a dbt_project. This will work if you just add this folder "helper" directly next to your DBT project. 
    """

    assert (run_mode in ["standalone", "package"])

    if run_mode == "standalone":
       
        path = Path(start_path).resolve()

        # Traverse up the directory tree
        while path != path.parent:
            dbt_file = path / 'dbt_project.yml'
            if dbt_file.is_file():
                return path
        
            path = path.parent

        return None
    
    elif run_mode == "package":
       
       try:
            # Create a Path object for the current script and resolve to an absolute path
            current_path = Path(__file__).resolve()

            # Navigate three levels up
            three_levels_up = current_path.parents[2]

            # Path of the 'dbt_project.yml' file three levels up
            dbt_project_file = three_levels_up / 'dbt_project.yml'

            # Check if the file exists
            if dbt_project_file.is_file():
                print(f"'dbt_project.yml' exists at {dbt_project_file}")
            else:
                print(f"'dbt_project.yml' does not exist at {dbt_project_file}")

            return None
       
       except Exception as e:
        print(f"WARNING: Unable to resolve dbt_project file in parent directory for package mode. Trying to find the dbt_project file anywhere. ")  
        path = Path(start_path).resolve()

        # Traverse up the directory tree
        while path != path.parent:
            dbt_file = path / 'dbt_project.yml'
            if dbt_file.is_file():
                return path

            path = path.parent

        return None
          
          
def find_helper_directory(start_path):

    path = Path(start_path).resolve()

    # Traverse up the directory tree
    while path != path.parent:
        helper_dir = path / 'helper'
        if helper_dir.is_dir():
            # Return the path of the 'helper' directory where the migration package is
            return helper_dir
        path = path.parent

    return None


## Function to load supported functions to convert from config folder
def get_functions_list(sourcedb):

    current_script = Path(__file__).resolve()

    parent_directory = current_script.parent

    file_path = parent_directory / '_resources/config' / sourcedb / 'functionlist.csv'

    print(f"FILE PATH: {file_path}")
    # Check if the file exists
    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    # Read the CSV file into a Pandas DataFrame
    input_functionspd = pd.read_csv(file_path)
    input_functions = input_functionspd["function_name"]
    return input_functions


## Function to load supported syntax maps to convert from config folder
def get_syntax_map(sourcedb):

    current_script = Path(__file__).resolve()

    parent_directory = current_script.parent

    file_path = parent_directory / '_resources/config' / sourcedb / 'syntax_mappings.json'

    print(f"FILE PATH: {file_path}")
    # Check if the file exists
    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(file_path, 'r') as file:
        syntax_map = json.load(file)

        return syntax_map


#### Main runner

if __name__ == '__main__':

    # Create the parser 
    parser = argparse.ArgumentParser(description='Local DBT to Databricks SQL Tranpiler')

    parser.add_argument("sourcedb", type=str, help='The database in which we are converting from - snowflake or redshift')
    parser.add_argument("--subdir_path", type=str, default = "", help="A sub-path under the models folder if you have multiple model folders and only want to convert one. Leave blank if you want all models parsed")
    parser.add_argument("--parse_mode", type=str, default = 'functions', help = "Flag stating whether to parse for functions, syntax, or all.")
    parser.add_argument("--run_mode", type=str, default = 'standalone', help = "'package' or 'standalone' mode. package mode is running within another DBT project as an import package. standalone is running in a DBT project directly. ")
    parser.add_argument("--output_folder", type=str, default = 'databricks', help = "Name of output directory of converted functions. 'databricks' by default under the models folder. Takes name of source folder and name of target foler to create output folder for each folder.")

    ### Script Arguments
    # Parse arguments
    args = parser.parse_args()

    ## Source Database
    if str(args.sourcedb).lower() not in ["snowflake", "redshift"]:
      raise(Exception("sourcedb must be either snowflake or Redshift"))
    else: 
      sourcedb = str(args.sourcedb).lower()

    ## Sub Model Path (or None)
    if len(args.subdir_path) > 1:
      subdirpath = str(args.subdir_path)
    else: 
      subdirpath = ""
    
    ## Source Database
    if str(args.parse_mode).lower() not in ["functions", "syntax", "all"]:
      raise(Exception("ERROR: Parse mode must be 'functions', 'syntax' or 'all'"))
    else: 
      parse_mode = str(args.parse_mode).lower()

    ## Run as package mode or standalone
    run_mode = args.run_mode


    print(f"\nDBT TRANSPILER: Transpiling to Databricks Macros from {sourcedb} functions... with run mode {run_mode}.\n")
    if len(subdirpath) > 1:
      print(f"Processing only the following model subdirectory {subdirpath}. \n")
    else:
      print(f"Processing all models under models folder. \n")


    # Start from the current script's directory
    project_base_directory = find_dbt_project_file(__file__, run_mode = run_mode)

    ## Load location of helper directory for library configs
    migration_utility_base_directory = find_helper_directory(__file__)


    if project_base_directory:
        print(f"Found 'dbt_project.yml' in: {project_base_directory}")
        # You can now use base_directory as your base path for further navigation
    else:
        raise("dbt_project.yml not found in any parent directories. Something is wrong with this project setup.")

    if migration_utility_base_directory:
        print(f"Found Migration Utility Folder {migration_utility_base_directory}")
        # You can now use base_directory as your base path for further navigation
    else:
        raise("Migration utility not found in any parent directories. Something is wrong with this project setup.")


    ## Load input functions from lakehouse utils file
    input_functions = get_functions_list(sourcedb = sourcedb)
    print(f"\nConverting the following functions from {sourcedb} to Databricks Dialect: \n {input_functions}")

    ## Load syntax regex mappings
    syntax_map = get_syntax_map(sourcedb= sourcedb)
    print(f"\nConverting the following syntax rules from {sourcedb} to Databricks Dialect: \n {syntax_map}")

    ## Now do project conversion
    dbt_project_functions_to_macros(base_project_path=project_base_directory, 
                                    input_functions=input_functions,
                                    subdirpath=subdirpath, 
                                    parse_mode = parse_mode,
                                    syntax_map= syntax_map)

