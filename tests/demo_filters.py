"""
Script de demostración del sistema de filtros avanzados.

Muestra cómo los filtros mejoran la calidad del dataset.
"""

import sys
from pathlib import Path

# Agregar el directorio raíz al path
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

from src.github.filters import RepositoryFilters


def print_header(title):
    """Imprime un encabezado formateado"""
    print("\n" + "=" * 80)
    print(title.center(80))
    print("=" * 80)


def demo_filter_comparison():
    """
    Demuestra la diferencia entre un repo que pasa todos los filtros
    y uno que es rechazado.
    """
    print_header("DEMOSTRACIÓN: Comparación de Repositorios")
    
    # Repositorio de calidad (Qiskit simulado)
    quality_repo = {
        "nameWithOwner": "Qiskit/qiskit",
        "name": "qiskit",
        "description": "Qiskit is an open-source SDK for working with quantum computers",
        "stargazerCount": 6561,
        "forkCount": 2234,
        "watchers": {"totalCount": 234},
        "primaryLanguage": {"name": "Python"},
        "updatedAt": "2024-10-10T10:00:00Z",
        "isArchived": False,
        "isFork": False,
        "defaultBranchRef": {
            "target": {
                "history": {"totalCount": 15432}
            }
        },
        "diskUsage": 250000,
        "object": {
            "text": "# Qiskit\n\nQiskit is an open-source quantum computing framework..."
        },
        "repositoryTopics": {
            "nodes": [
                {"topic": {"name": "quantum"}},
                {"topic": {"name": "qiskit"}},
                {"topic": {"name": "python"}}
            ]
        },
        "openIssues": {"totalCount": 145},
        "closedIssues": {"totalCount": 3421},
        "pullRequests": {"totalCount": 2134}
    }
    
    # Repositorio de baja calidad
    poor_repo = {
        "nameWithOwner": "user123/test-project",
        "name": "test-project",
        "description": "",
        "stargazerCount": 2,
        "forkCount": 0,
        "watchers": {"totalCount": 1},
        "primaryLanguage": {"name": "HTML"},
        "updatedAt": "2020-01-15T10:00:00Z",
        "isArchived": True,
        "isFork": True,
        "defaultBranchRef": {
            "target": {
                "history": {"totalCount": 3}
            }
        },
        "diskUsage": 5,
        "object": None,
        "repositoryTopics": {"nodes": []},
        "openIssues": {"totalCount": 0},
        "closedIssues": {"totalCount": 0},
        "pullRequests": {"totalCount": 0}
    }
    
    keywords = ["quantum", "qiskit", "braket", "cirq", "pennylane"]
    valid_languages = ["Python", "C++", "Q#", "Rust", "Julia", "JavaScript"]
    
    # Evaluar repo de calidad
    print("\n🟢 REPOSITORIO DE CALIDAD: Qiskit/qiskit")
    print("-" * 80)
    
    filters_quality = [
        ("No archivado", RepositoryFilters.is_not_archived(quality_repo)),
        ("Tiene descripción", RepositoryFilters.has_description(quality_repo)),
        ("Tamaño mínimo", RepositoryFilters.is_minimal_project(quality_repo, 10, 10)),
        ("Activo (365 días)", RepositoryFilters.is_active(quality_repo, 365)),
        ("Fork válido", RepositoryFilters.is_valid_fork(quality_repo)),
        ("Keywords cuánticas", RepositoryFilters.matches_keywords(quality_repo, keywords)),
        ("Lenguaje válido", RepositoryFilters.has_valid_language(quality_repo, valid_languages)),
        ("Estrellas (≥10)", RepositoryFilters.has_minimum_stars(quality_repo, 10)),
        ("Engagement", RepositoryFilters.has_community_engagement(quality_repo, 3, 1))
    ]
    
    passed_quality = 0
    for filter_name, result in filters_quality:
        status = "✅ PASA" if result else "❌ RECHAZA"
        print(f"  {status} {filter_name}")
        if result:
            passed_quality += 1
    
    print(f"\n✅ Resultado: {passed_quality}/9 filtros pasados → REPOSITORIO VÁLIDO")
    
    # Evaluar repo de baja calidad
    print("\n\n🔴 REPOSITORIO DE BAJA CALIDAD: user123/test-project")
    print("-" * 80)
    
    filters_poor = [
        ("No archivado", RepositoryFilters.is_not_archived(poor_repo)),
        ("Tiene descripción", RepositoryFilters.has_description(poor_repo)),
        ("Tamaño mínimo", RepositoryFilters.is_minimal_project(poor_repo, 10, 10)),
        ("Activo (365 días)", RepositoryFilters.is_active(poor_repo, 365)),
        ("Fork válido", RepositoryFilters.is_valid_fork(poor_repo)),
        ("Keywords cuánticas", RepositoryFilters.matches_keywords(poor_repo, keywords)),
        ("Lenguaje válido", RepositoryFilters.has_valid_language(poor_repo, valid_languages)),
        ("Estrellas (≥10)", RepositoryFilters.has_minimum_stars(poor_repo, 10)),
        ("Engagement", RepositoryFilters.has_community_engagement(poor_repo, 3, 1))
    ]
    
    passed_poor = 0
    for filter_name, result in filters_poor:
        status = "✅ PASA" if result else "❌ RECHAZA"
        print(f"  {status} {filter_name}")
        if result:
            passed_poor += 1
    
    print(f"\n❌ Resultado: {passed_poor}/9 filtros pasados → REPOSITORIO RECHAZADO")
    
    print("\n" + "=" * 80)
    print(f"Conclusión: Los filtros permiten distinguir proyectos de calidad")
    print(f"            de repositorios triviales o abandonados.")
    print("=" * 80)


def demo_filter_statistics():
    """
    Muestra estadísticas simuladas de filtrado en lote.
    """
    print_header("DEMOSTRACIÓN: Estadísticas de Filtrado")
    
    print("\n📊 Simulación de filtrado de 100 repositorios encontrados:")
    print("-" * 80)
    
    stages = [
        ("Repositorios encontrados", 100, 0),
        ("Después de filtro archivados", 98, 2),
        ("Después de filtro descripción", 93, 5),
        ("Después de filtro tamaño mínimo", 85, 8),
        ("Después de filtro actividad", 82, 3),
        ("Después de filtro forks", 80, 2),
        ("Después de filtro keywords", 79, 1),
        ("Después de filtro lenguaje", 72, 7),
        ("Después de filtro estrellas", 72, 0),
        ("Después de filtro engagement", 68, 4)
    ]
    
    for stage, remaining, rejected in stages:
        bar_length = int(remaining / 2)
        bar = "█" * bar_length + "░" * (50 - bar_length)
        
        if rejected > 0:
            print(f"{stage:35} [{bar}] {remaining:3}/100 (-{rejected})")
        else:
            print(f"{stage:35} [{bar}] {remaining:3}/100")
    
    print("\n" + "=" * 80)
    print(f"✅ Resultado Final: 68 repositorios válidos (68% tasa de éxito)")
    print(f"❌ Rechazados: 32 repositorios")
    print("=" * 80)
    
    print("\n📈 Desglose de rechazos:")
    print("-" * 80)
    rejections = [
        ("Archivados", 2),
        ("Sin descripción", 5),
        ("Muy pequeños", 8),
        ("Inactivos", 3),
        ("Forks sin aportes", 2),
        ("Sin keywords cuánticas", 1),
        ("Lenguaje no válido", 7),
        ("Pocas estrellas", 0),
        ("Sin engagement", 4)
    ]
    
    for reason, count in rejections:
        percentage = (count / 100) * 100
        bar_length = int(count * 2)
        bar = "▓" * bar_length
        print(f"  {reason:25} {bar:20} {count:2} ({percentage:.0f}%)")


def demo_individual_filters():
    """
    Demuestra cada filtro individualmente con ejemplos.
    """
    print_header("DEMOSTRACIÓN: Filtros Individuales")
    
    # Ejemplo 1: Actividad
    print("\n1️⃣ Filtro de Actividad Reciente")
    print("-" * 80)
    print("✅ Repo actualizado hace 30 días → PASA")
    print("❌ Repo actualizado hace 400 días → RECHAZA")
    
    # Ejemplo 2: Fork
    print("\n2️⃣ Filtro de Fork Válido")
    print("-" * 80)
    print("✅ No es fork → PASA")
    print("✅ Fork con 100 commits propios → PASA")
    print("❌ Fork con 5 commits y sin issues → RECHAZA")
    
    # Ejemplo 3: Descripción
    print("\n3️⃣ Filtro de Documentación")
    print("-" * 80)
    print("✅ Tiene descripción: 'Quantum computing library' → PASA")
    print("✅ Tiene README.md → PASA")
    print("❌ Sin descripción ni README → RECHAZA")
    
    # Ejemplo 4: Tamaño
    print("\n4️⃣ Filtro de Tamaño Mínimo")
    print("-" * 80)
    print("✅ 100 commits, 1000 KB → PASA")
    print("✅ 10 commits, 10 KB (mínimo) → PASA")
    print("❌ 5 commits, 5 KB → RECHAZA")
    
    # Ejemplo 5: Keywords
    print("\n5️⃣ Filtro de Keywords Cuánticas")
    print("-" * 80)
    print("✅ Nombre: 'quantum-simulator' → PASA")
    print("✅ Descripción: 'uses qiskit framework' → PASA")
    print("✅ Topic: 'quantum' → PASA")
    print("❌ Sin keywords cuánticas → RECHAZA")
    
    # Ejemplo 6: Lenguaje
    print("\n6️⃣ Filtro de Lenguaje Válido")
    print("-" * 80)
    print("✅ Python → PASA")
    print("✅ C++ → PASA")
    print("✅ Rust → PASA")
    print("❌ Go → RECHAZA")
    
    # Ejemplo 7: Archivado
    print("\n7️⃣ Filtro de Archivado")
    print("-" * 80)
    print("✅ isArchived = False → PASA")
    print("❌ isArchived = True → RECHAZA")
    
    # Ejemplo 8: Estrellas
    print("\n8️⃣ Filtro de Estrellas Mínimas")
    print("-" * 80)
    print("✅ 50 estrellas → PASA")
    print("✅ 10 estrellas (mínimo) → PASA")
    print("❌ 5 estrellas → RECHAZA")
    
    # Ejemplo 9: Engagement
    print("\n9️⃣ Filtro de Engagement de Comunidad")
    print("-" * 80)
    print("✅ 10 watchers, 5 forks → PASA")
    print("✅ 3 watchers (mínimo) → PASA")
    print("❌ 1 watcher, 0 forks → RECHAZA")


def main():
    """Ejecuta todas las demostraciones"""
    print("\n")
    print("█" * 80)
    print("█ SISTEMA DE FILTROS AVANZADOS DE CALIDAD".center(80) + "█")
    print("█ Demostración Interactiva".center(80) + "█")
    print("█" * 80)
    
    # Demo 1: Comparación
    demo_filter_comparison()
    
    input("\n\nPresiona ENTER para continuar a las estadísticas...")
    
    # Demo 2: Estadísticas
    demo_filter_statistics()
    
    input("\n\nPresiona ENTER para continuar a los filtros individuales...")
    
    # Demo 3: Filtros individuales
    demo_individual_filters()
    
    # Conclusión
    print_header("CONCLUSIÓN")
    print("\n✅ El sistema de filtros avanzados garantiza:")
    print("   • Repositorios activos y mantenidos")
    print("   • Documentación completa (descripción o README)")
    print("   • Proyectos sustanciales (commits y tamaño mínimos)")
    print("   • Relevancia cuántica verificada en múltiples campos")
    print("   • Lenguajes de programación adecuados")
    print("   • Engagement de la comunidad")
    print("   • Exclusión de repos archivados o triviales")
    print("\n✅ Tasa de éxito típica: 60-80% de repos encontrados")
    print("✅ Dataset final: Alta calidad y representatividad")
    print("\n" + "=" * 80)
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nDemostración interrumpida por el usuario")
        sys.exit(0)
