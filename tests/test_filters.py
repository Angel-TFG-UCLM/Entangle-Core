"""
Tests para los filtros avanzados de calidad de repositorios.

Prueba cada filtro de forma individual y el conjunto completo.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

# Agregar el directorio raíz al path
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

from src.github.filters import RepositoryFilters
import logging

# Configurar logging básico para los tests
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_test_repo(
    name: str = "test/quantum-repo",
    description: str = "A quantum computing library",
    is_fork: bool = False,
    is_archived: bool = False,
    stars: int = 50,
    language: str = "Python",
    updated_days_ago: int = 30,
    commit_count: int = 100,
    disk_usage_kb: int = 1000,
    has_readme: bool = True,
    watchers: int = 10,
    forks: int = 5,
    open_issues: int = 5,
    closed_issues: int = 10,
    pull_requests: int = 3
) -> dict:
    """
    Crea un repositorio de prueba con los parámetros especificados.
    """
    updated_at = datetime.now(timezone.utc) - timedelta(days=updated_days_ago)
    
    repo = {
        "id": "test123",
        "name": name.split("/")[-1] if "/" in name else name,
        "nameWithOwner": name,
        "description": description,
        "isFork": is_fork,
        "isArchived": is_archived,
        "stargazerCount": stars,
        "primaryLanguage": {"name": language} if language else None,
        "updatedAt": updated_at.isoformat(),
        "pushedAt": updated_at.isoformat(),
        "defaultBranchRef": {
            "name": "main",
            "target": {
                "history": {
                    "totalCount": commit_count
                }
            }
        } if commit_count > 0 else None,
        "diskUsage": disk_usage_kb,
        "object": {
            "text": "# README\nThis is a quantum computing project."
        } if has_readme else None,
        "watchers": {
            "totalCount": watchers
        },
        "forkCount": forks,
        "openIssues": {
            "totalCount": open_issues
        },
        "closedIssues": {
            "totalCount": closed_issues
        },
        "pullRequests": {
            "totalCount": pull_requests
        },
        "repositoryTopics": {
            "nodes": [
                {"topic": {"name": "quantum"}},
                {"topic": {"name": "qiskit"}}
            ]
        }
    }
    
    return repo


def test_is_active():
    """Test 1: Filtro de actividad reciente"""
    print("\n" + "=" * 80)
    print("TEST 1: Filtro de Actividad Reciente")
    print("=" * 80)
    
    # Repo activo (actualizado hace 30 días)
    active_repo = create_test_repo(updated_days_ago=30)
    result = RepositoryFilters.is_active(active_repo, max_inactivity_days=365)
    print(f"✓ Repo activo (30 días): {result}")
    assert result == True, "Repo activo debería pasar el filtro"
    
    # Repo inactivo (actualizado hace 400 días)
    inactive_repo = create_test_repo(updated_days_ago=400)
    result = RepositoryFilters.is_active(inactive_repo, max_inactivity_days=365)
    print(f"✓ Repo inactivo (400 días): {result}")
    assert result == False, "Repo inactivo debería ser rechazado"
    
    print("✅ Test de actividad PASADO")
    return True


def test_is_valid_fork():
    """Test 2: Filtro de forks válidos"""
    print("\n" + "=" * 80)
    print("TEST 2: Filtro de Forks Válidos")
    print("=" * 80)
    
    # No es fork (siempre válido)
    not_fork = create_test_repo(is_fork=False)
    result = RepositoryFilters.is_valid_fork(not_fork)
    print(f"✓ No es fork: {result}")
    assert result == True, "Repo que no es fork debería pasar"
    
    # Fork con contribuciones propias (100 commits)
    valid_fork = create_test_repo(is_fork=True, commit_count=100, open_issues=10)
    result = RepositoryFilters.is_valid_fork(valid_fork)
    print(f"✓ Fork con 100 commits: {result}")
    assert result == True, "Fork con contribuciones debería pasar"
    
    # Fork sin contribuciones (5 commits, 0 issues)
    invalid_fork = create_test_repo(
        is_fork=True,
        commit_count=5,
        open_issues=0,
        closed_issues=0,
        pull_requests=0
    )
    result = RepositoryFilters.is_valid_fork(invalid_fork)
    print(f"✓ Fork sin contribuciones (5 commits, 0 issues): {result}")
    assert result == False, "Fork sin contribuciones debería ser rechazado"
    
    print("✅ Test de forks válidos PASADO")
    return True


def test_has_description():
    """Test 3: Filtro de descripción/README"""
    print("\n" + "=" * 80)
    print("TEST 3: Filtro de Descripción/README")
    print("=" * 80)
    
    # Con descripción y README
    with_both = create_test_repo(description="Quantum library", has_readme=True)
    result = RepositoryFilters.has_description(with_both)
    print(f"✓ Con descripción y README: {result}")
    assert result == True, "Repo con ambos debería pasar"
    
    # Solo con descripción
    with_desc = create_test_repo(description="Quantum library", has_readme=False)
    result = RepositoryFilters.has_description(with_desc)
    print(f"✓ Solo con descripción: {result}")
    assert result == True, "Repo con descripción debería pasar"
    
    # Sin descripción ni README
    without_both = create_test_repo(description="", has_readme=False)
    result = RepositoryFilters.has_description(without_both)
    print(f"✓ Sin descripción ni README: {result}")
    assert result == False, "Repo sin documentación debería ser rechazado"
    
    print("✅ Test de descripción PASADO")
    return True


def test_is_minimal_project():
    """Test 4: Filtro de tamaño mínimo"""
    print("\n" + "=" * 80)
    print("TEST 4: Filtro de Tamaño Mínimo")
    print("=" * 80)
    
    # Proyecto grande (100 commits, 1000 KB)
    large_project = create_test_repo(commit_count=100, disk_usage_kb=1000)
    result = RepositoryFilters.is_minimal_project(large_project, min_commits=10, min_size_kb=10)
    print(f"✓ Proyecto grande (100 commits, 1000 KB): {result}")
    assert result == True, "Proyecto grande debería pasar"
    
    # Proyecto mínimo (10 commits, 10 KB)
    minimal_project = create_test_repo(commit_count=10, disk_usage_kb=10)
    result = RepositoryFilters.is_minimal_project(minimal_project, min_commits=10, min_size_kb=10)
    print(f"✓ Proyecto mínimo (10 commits, 10 KB): {result}")
    assert result == True, "Proyecto mínimo debería pasar"
    
    # Proyecto muy pequeño (5 commits, 5 KB)
    tiny_project = create_test_repo(commit_count=5, disk_usage_kb=5)
    result = RepositoryFilters.is_minimal_project(tiny_project, min_commits=10, min_size_kb=10)
    print(f"✓ Proyecto muy pequeño (5 commits, 5 KB): {result}")
    assert result == False, "Proyecto muy pequeño debería ser rechazado"
    
    print("✅ Test de tamaño mínimo PASADO")
    return True


def test_matches_keywords():
    """Test 5: Filtro de keywords cuánticas"""
    print("\n" + "=" * 80)
    print("TEST 5: Filtro de Keywords Cuánticas")
    print("=" * 80)
    
    keywords = ["quantum", "qiskit", "braket", "cirq", "pennylane"]
    
    # Repo con keyword en nombre
    in_name = create_test_repo(name="test/quantum-simulator")
    result = RepositoryFilters.matches_keywords(in_name, keywords)
    print(f"✓ Keyword en nombre ('quantum-simulator'): {result}")
    assert result == True, "Repo con keyword en nombre debería pasar"
    
    # Repo con keyword en descripción
    in_desc = create_test_repo(
        name="test/simulator",
        description="A simulator using qiskit framework"
    )
    result = RepositoryFilters.matches_keywords(in_desc, keywords)
    print(f"✓ Keyword en descripción ('qiskit'): {result}")
    assert result == True, "Repo con keyword en descripción debería pasar"
    
    # Repo sin keywords cuánticas
    no_keywords = {
        "id": "test456",
        "name": "random-project",
        "nameWithOwner": "test/random-project",
        "description": "A random machine learning library",
        "object": {
            "text": "# Random ML Project\nThis is about machine learning"
        },
        "repositoryTopics": {"nodes": []}
    }
    result = RepositoryFilters.matches_keywords(no_keywords, keywords)
    print(f"✓ Sin keywords cuánticas: {result}")
    assert result == False, "Repo sin keywords debería ser rechazado"
    
    print("✅ Test de keywords PASADO")
    return True


def test_has_valid_language():
    """Test 6: Filtro de lenguaje válido"""
    print("\n" + "=" * 80)
    print("TEST 6: Filtro de Lenguaje Válido")
    print("=" * 80)
    
    valid_languages = ["Python", "C++", "Q#", "Rust", "Julia", "JavaScript"]
    
    # Lenguaje válido (Python)
    python_repo = create_test_repo(language="Python")
    result = RepositoryFilters.has_valid_language(python_repo, valid_languages)
    print(f"✓ Lenguaje Python: {result}")
    assert result == True, "Python debería ser válido"
    
    # Lenguaje válido (Rust)
    rust_repo = create_test_repo(language="Rust")
    result = RepositoryFilters.has_valid_language(rust_repo, valid_languages)
    print(f"✓ Lenguaje Rust: {result}")
    assert result == True, "Rust debería ser válido"
    
    # Lenguaje no válido (Go)
    go_repo = create_test_repo(language="Go")
    result = RepositoryFilters.has_valid_language(go_repo, valid_languages)
    print(f"✓ Lenguaje Go: {result}")
    assert result == False, "Go no debería ser válido"
    
    print("✅ Test de lenguaje PASADO")
    return True


def test_is_not_archived():
    """Test 7: Filtro de archivado"""
    print("\n" + "=" * 80)
    print("TEST 7: Filtro de Archivado")
    print("=" * 80)
    
    # No archivado
    not_archived = create_test_repo(is_archived=False)
    result = RepositoryFilters.is_not_archived(not_archived)
    print(f"✓ Repo no archivado: {result}")
    assert result == True, "Repo no archivado debería pasar"
    
    # Archivado
    archived = create_test_repo(is_archived=True)
    result = RepositoryFilters.is_not_archived(archived)
    print(f"✓ Repo archivado: {result}")
    assert result == False, "Repo archivado debería ser rechazado"
    
    print("✅ Test de archivado PASADO")
    return True


def test_has_minimum_stars():
    """Test 8: Filtro de estrellas mínimas"""
    print("\n" + "=" * 80)
    print("TEST 8: Filtro de Estrellas Mínimas")
    print("=" * 80)
    
    # Con suficientes estrellas
    popular = create_test_repo(stars=50)
    result = RepositoryFilters.has_minimum_stars(popular, min_stars=10)
    print(f"✓ Repo con 50 estrellas (mínimo 10): {result}")
    assert result == True, "Repo con 50 estrellas debería pasar"
    
    # Con estrellas justas
    just_enough = create_test_repo(stars=10)
    result = RepositoryFilters.has_minimum_stars(just_enough, min_stars=10)
    print(f"✓ Repo con 10 estrellas (mínimo 10): {result}")
    assert result == True, "Repo con 10 estrellas debería pasar"
    
    # Con pocas estrellas
    unpopular = create_test_repo(stars=5)
    result = RepositoryFilters.has_minimum_stars(unpopular, min_stars=10)
    print(f"✓ Repo con 5 estrellas (mínimo 10): {result}")
    assert result == False, "Repo con 5 estrellas debería ser rechazado"
    
    print("✅ Test de estrellas PASADO")
    return True


def test_has_community_engagement():
    """Test 9: Filtro de engagement de comunidad"""
    print("\n" + "=" * 80)
    print("TEST 9: Filtro de Engagement de Comunidad")
    print("=" * 80)
    
    # Con buen engagement (watchers y forks)
    good_engagement = create_test_repo(watchers=10, forks=5)
    result = RepositoryFilters.has_community_engagement(good_engagement, min_watchers=3, min_forks=1)
    print(f"✓ Repo con 10 watchers y 5 forks: {result}")
    assert result == True, "Repo con buen engagement debería pasar"
    
    # Con engagement mínimo (solo watchers)
    min_engagement = create_test_repo(watchers=3, forks=0)
    result = RepositoryFilters.has_community_engagement(min_engagement, min_watchers=3, min_forks=1)
    print(f"✓ Repo con 3 watchers y 0 forks: {result}")
    assert result == True, "Repo con engagement mínimo debería pasar"
    
    # Sin engagement
    no_engagement = create_test_repo(watchers=1, forks=0)
    result = RepositoryFilters.has_community_engagement(no_engagement, min_watchers=3, min_forks=1)
    print(f"✓ Repo con 1 watcher y 0 forks: {result}")
    assert result == False, "Repo sin engagement debería ser rechazado"
    
    print("✅ Test de engagement PASADO")
    return True


def test_complete_filter_chain():
    """Test 10: Cadena completa de filtros"""
    print("\n" + "=" * 80)
    print("TEST 10: Cadena Completa de Filtros")
    print("=" * 80)
    
    # Repo perfecto (pasa todos los filtros)
    perfect_repo = create_test_repo(
        name="test/qiskit-quantum",
        description="Quantum computing with qiskit",
        is_fork=False,
        is_archived=False,
        stars=100,
        language="Python",
        updated_days_ago=10,
        commit_count=200,
        disk_usage_kb=5000,
        has_readme=True,
        watchers=20,
        forks=10
    )
    
    keywords = ["quantum", "qiskit"]
    valid_languages = ["Python", "C++"]
    
    filters = [
        ("is_not_archived", RepositoryFilters.is_not_archived(perfect_repo)),
        ("is_active", RepositoryFilters.is_active(perfect_repo, 365)),
        ("is_valid_fork", RepositoryFilters.is_valid_fork(perfect_repo)),
        ("has_description", RepositoryFilters.has_description(perfect_repo)),
        ("is_minimal_project", RepositoryFilters.is_minimal_project(perfect_repo, 10, 10)),
        ("matches_keywords", RepositoryFilters.matches_keywords(perfect_repo, keywords)),
        ("has_valid_language", RepositoryFilters.has_valid_language(perfect_repo, valid_languages)),
        ("has_minimum_stars", RepositoryFilters.has_minimum_stars(perfect_repo, 10)),
        ("has_community_engagement", RepositoryFilters.has_community_engagement(perfect_repo, 3, 1))
    ]
    
    print("Aplicando filtros al repo perfecto:")
    for filter_name, result in filters:
        status = "✓" if result else "✗"
        print(f"  {status} {filter_name}: {result}")
        assert result == True, f"Repo perfecto debería pasar {filter_name}"
    
    print("\n✅ Test de cadena completa PASADO")
    return True


def main():
    """Ejecuta todos los tests"""
    print("\n" + "=" * 80)
    print("TESTS DE FILTROS AVANZADOS")
    print("=" * 80)
    
    tests = [
        ("Actividad reciente", test_is_active),
        ("Forks válidos", test_is_valid_fork),
        ("Descripción/README", test_has_description),
        ("Tamaño mínimo", test_is_minimal_project),
        ("Keywords cuánticas", test_matches_keywords),
        ("Lenguaje válido", test_has_valid_language),
        ("No archivado", test_is_not_archived),
        ("Estrellas mínimas", test_has_minimum_stars),
        ("Engagement comunidad", test_has_community_engagement),
        ("Cadena completa", test_complete_filter_chain)
    ]
    
    results = []
    
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ Error en test '{name}': {e}")
            logger.error(f"Error en test '{name}': {e}", exc_info=True)
            results.append((name, False))
    
    # Resumen final
    print("\n" + "=" * 80)
    print("RESUMEN DE TESTS")
    print("=" * 80)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {name}")
    
    print(f"\nResultado: {passed}/{total} tests pasados")
    print(f"Tasa de éxito: {(passed/total*100):.1f}%")
    print("=" * 80)
    
    return passed == total


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTests interrumpidos por el usuario")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Error fatal: {e}")
        logger.error(f"Error fatal en tests: {e}", exc_info=True)
        sys.exit(1)
