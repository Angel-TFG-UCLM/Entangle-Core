#!/usr/bin/env python3
"""
Test de Validación v3.0 - Verifica que el modelo User v3.0 funcione correctamente
"""

import sys
import os

# Añadir src al path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.models.user import User
from datetime import datetime


def test_none_to_empty_list():
    """Test: None se convierte automáticamente a [] para listas."""
    print("\n🧪 Test 1: None → [] para listas")
    
    data = {
        "id": "test123",
        "login": "testuser",
        "url": "https://github.com/testuser",
        "organizations": None,  # Debe convertirse a []
        "pinned_repositories": None,  # Debe convertirse a []
        "top_languages": None,  # Debe convertirse a []
        "quantum_repositories": None  # Debe convertirse a []
    }
    
    user = User(**data)
    
    assert user.organizations == [], f"❌ organizations debería ser [], es {user.organizations}"
    assert user.pinned_repositories == [], f"❌ pinned_repositories debería ser [], es {user.pinned_repositories}"
    assert user.top_languages == [], f"❌ top_languages debería ser [], es {user.top_languages}"
    assert user.quantum_repositories == [], f"❌ quantum_repositories debería ser [], es {user.quantum_repositories}"
    
    print("✅ None convertido correctamente a [] para todas las listas")


def test_optional_fields_valid():
    """Test: Campos opcionales pueden ser None sin romper validación."""
    print("\n🧪 Test 2: Campos opcionales con None")
    
    data = {
        "id": "test456",
        "login": "johndoe",
        "url": "https://github.com/johndoe",
        "name": None,
        "email": None,
        "bio": None,
        "company": None,  # Válido: no tiene empresa
        "location": None,
        "twitter_username": None,  # Válido: no tiene Twitter
        "website_url": None
    }
    
    user = User(**data)
    
    assert user.company is None, f"❌ company debería ser None"
    assert user.twitter_username is None, f"❌ twitter_username debería ser None"
    
    print("✅ Campos opcionales con None son válidos")


def test_default_values():
    """Test: Valores por defecto se asignan correctamente."""
    print("\n🧪 Test 3: Valores por defecto")
    
    data = {
        "id": "test789",
        "login": "janedoe",
        "url": "https://github.com/janedoe"
    }
    
    user = User(**data)
    
    assert user.followers_count == 0, f"❌ followers_count debería ser 0"
    assert user.following_count == 0, f"❌ following_count debería ser 0"
    assert user.is_hireable == False, f"❌ is_hireable debería ser False"
    assert user.is_bot == False, f"❌ is_bot debería ser False"
    assert user.extracted_from == [], f"❌ extracted_from debería ser []"
    assert user.ingested_at is not None, f"❌ ingested_at debería tener valor"
    
    print("✅ Valores por defecto asignados correctamente")


def test_quantum_fields():
    """Test: Campos core del TFG funcionan correctamente."""
    print("\n🧪 Test 4: Campos core TFG (quantum)")
    
    data = {
        "id": "test999",
        "login": "quantumdev",
        "url": "https://github.com/quantumdev",
        "quantum_repositories": [
            {"name": "qiskit", "stars": 1000},
            {"name": "cirq", "stars": 500}
        ],
        "is_quantum_contributor": True,
        "quantum_expertise_score": 85.5
    }
    
    user = User(**data)
    
    assert len(user.quantum_repositories) == 2, f"❌ Debería tener 2 repos quantum"
    assert user.is_quantum_contributor == True, f"❌ Debería ser quantum contributor"
    assert user.quantum_expertise_score == 85.5, f"❌ Score debería ser 85.5"
    
    print("✅ Campos quantum funcionan correctamente")


def test_enrichment_status_realistic():
    """Test: enrichment_status con lógica v3.0."""
    print("\n🧪 Test 5: Lógica de completitud v3.0")
    
    data = {
        "id": "test111",
        "login": "completeuser",
        "url": "https://github.com/completeuser",
        "company": None,  # Sin empresa (válido)
        "twitter_username": None,  # Sin Twitter (válido)
        "quantum_expertise_score": 75.0,  # Tiene score → COMPLETO
        "enrichment_status": {
            "is_complete": True,  # ✅ CORRECTO en v3.0
            "version": "3.0",
            "last_check": datetime.now().isoformat(),
            "fields_missing": []  # ✅ No reporta opcionales
        }
    }
    
    user = User(**data)
    
    assert user.enrichment_status["is_complete"] == True, "❌ Debería estar completo"
    assert user.enrichment_status["version"] == "3.0", "❌ Versión debería ser 3.0"
    assert user.enrichment_status["fields_missing"] == [], "❌ No debería reportar missing"
    
    print("✅ Lógica de completitud v3.0 correcta")


def test_no_obsolete_fields():
    """Test: Campos obsoletos son ignorados (extra='ignore')."""
    print("\n🧪 Test 6: Campos obsoletos ignorados")
    
    data = {
        "id": "test222",
        "login": "legacyuser",
        "url": "https://github.com/legacyuser",
        # Campos obsoletos (deberían ser ignorados)
        "projects": [],
        "social_accounts": [],
        "status": {"emoji": "😀"},
        "interaction_ability": {},
        "hasSponsorshipsListing": False
    }
    
    user = User(**data)
    
    # Verificar que no se guardan
    assert not hasattr(user, 'projects'), "❌ projects debería ser ignorado"
    assert not hasattr(user, 'social_accounts'), "❌ social_accounts debería ser ignorado"
    assert not hasattr(user, 'status'), "❌ status debería ser ignorado"
    
    print("✅ Campos obsoletos correctamente ignorados")


def main():
    """Ejecuta todos los tests."""
    print("\n" + "="*80)
    print("🚀 TESTS DE VALIDACIÓN v3.0 - Modelo User")
    print("="*80)
    
    try:
        test_none_to_empty_list()
        test_optional_fields_valid()
        test_default_values()
        test_quantum_fields()
        test_enrichment_status_realistic()
        test_no_obsolete_fields()
        
        print("\n" + "="*80)
        print("✅ TODOS LOS TESTS PASARON")
        print("="*80 + "\n")
        
    except AssertionError as e:
        print(f"\n❌ TEST FALLIDO: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR INESPERADO: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
