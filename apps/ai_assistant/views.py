import os
from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from apps.inventory.models import StockProjection, ProductSKU, Warehouse
from google import genai

@login_required
def chat_view(request):
    return render(request, 'ai_assistant/chat.html')

@login_required
def query_api_view(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
        
    user_prompt = request.POST.get('prompt', '').strip()
    if not user_prompt:
        return JsonResponse({'error': 'Prompt no proporcionado'}, status=400)
        
    api_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')
    
    # Extraer contexto relevante de la base de datos (RAG simplificado sobre DB)
    top_urgentes = StockProjection.objects.filter(urgency_level='URGENTE').order_by('-shortage_usd')[:10]
    context_str = "CONTEXTO DE INVENTARIO PESCO S.A.:\n"
    for proj in top_urgentes:
        context_str += f"- SKU: {proj.product.code} | Desc: {proj.product.description} | Bodega: {proj.warehouse.code if proj.warehouse else 'Global'} | Sugerido Compra: {proj.suggested_buy_units} u | Quiebre USD: ${proj.shortage_usd}\n"
        
    if not api_key:
        response_text = f"🤖 [Modo Simulado - Configura GEMINI_API_KEY en tu .env]\n\nBasándome en los datos del sistema Pesco S.A.:\nFound {top_urgentes.count()} SKUs urgentes.\n\nContexto analizado:\n{context_str}"
        return JsonResponse({'reply': response_text})
        
    try:
        client = genai.Client(api_key=api_key)
        full_prompt = f"Eres un Asistente Senior S&OP para Pesco S.A. Responde en español formal y preciso utilizando el siguiente contexto de base de datos:\n\n{context_str}\n\nPregunta del Usuario: {user_prompt}"
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=full_prompt,
        )
        return JsonResponse({'reply': response.text})
    except Exception as e:
        return JsonResponse({'reply': f"Error al comunicar con la API de Gemini: {str(e)}"})
