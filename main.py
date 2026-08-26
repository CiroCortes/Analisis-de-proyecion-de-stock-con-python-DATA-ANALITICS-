import subprocess
import sys
import os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

def run_script(script_path):
    print(f"\n{'='*50}")
    print(f"🚀 EJECUTANDO: {script_path}")
    print(f"{'='*50}")
    
    try:
        # Run the script and stream the output to the console
        result = subprocess.run([sys.executable, script_path], check=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n❌ ERROR FATAL: El script {script_path} falló.")
        return False

def main():
    print("="*65)
    print("      🏭 SISTEMA DE GESTIÓN DE STOCK PESCO S.A. - PIPELINE PRINCIPAL")
    print("="*65)
    
    scripts = [
        "src/clean_data.py",
        "src/eda_kpis.py",
        "src/stock_projection.py",
    ]
    
    # Also check if visualizations.py or generate_pdf.py exists and add them
    if os.path.exists("src/visualizations.py"):
        scripts.append("src/visualizations.py")
    if os.path.exists("src/generate_pdf.py"):
        scripts.append("src/generate_pdf.py")

    for script in scripts:
        if not os.path.exists(script):
            print(f"⚠️ ADVERTENCIA: No se encontró el script {script}, omitiendo...")
            continue
            
        success = run_script(script)
        if not success:
            print("\n🛑 Ejecución detenida debido a un error previo.")
            sys.exit(1)
            
    print("\n" + "="*50)
    print("🎉 ¡TODOS LOS SCRIPTS SE EJECUTARON CON ÉXITO! 🎉")
    print("="*50)

if __name__ == "__main__":
    main()
