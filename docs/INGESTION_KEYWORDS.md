# Entangle ingestion keyword taxonomy

This document exposes the exact keyword configuration used by the Entangle
repository-ingestion pipeline. The source of truth is
[`config/ingestion_config.json`](../config/ingestion_config.json), version 3.0.

## How the pipeline uses the lists

The two lists serve different purposes:

1. **GitHub discovery (`search_keywords`)**: each of these 8 terms starts an
   independent segmented GitHub search.
2. **Repository relevance (`keywords`)**: the full 71-term taxonomy is applied
   after discovery against the repository name, description, topics, and the
   first 500 characters of its README.

With the current 6 star ranges and 11 creation years, a complete segmented run
can generate up to `8 × 6 × 11 = 528` search segments before incremental-date
and result-limit constraints are applied.

## GitHub discovery terms (8)

1. `quantum`
2. `qiskit`
3. `cirq`
4. `pennylane`
5. `braket`
6. `pyquil`
7. `openqasm`
8. `projectq`

## Full relevance taxonomy (71)

1. `quantum`
2. `qiskit`
3. `braket`
4. `cirq`
5. `pennylane`
6. `quantum computing`
7. `quantum algorithms`
8. `quantum machine learning`
9. `qml`
10. `qubit`
11. `quantum simulator`
12. `quantum circuit`
13. `quantum annealing`
14. `quantum optimization`
15. `quantum cryptography`
16. `quantum teleportation`
17. `quantum entanglement`
18. `quantum superposition`
19. `quantum gates`
20. `quantum error correction`
21. `quantum chemistry`
22. `quantum mechanics`
23. `quantum physics`
24. `quantum programming`
25. `quantum software`
26. `quantum hardware`
27. `quantum processor`
28. `quantum computer`
29. `qpu`
30. `qaoa`
31. `vqe`
32. `quil`
33. `openqasm`
34. `qasm`
35. `pyquil`
36. `strawberry fields`
37. `projectq`
38. `quantum inspire`
39. `quantum development kit`
40. `forest`
41. `rigetti`
42. `ionq`
43. `d-wave`
44. `ibm quantum`
45. `google quantum`
46. `azure quantum`
47. `aws quantum`
48. `quantum supremacy`
49. `quantum advantage`
50. `nisq`
51. `fault-tolerant`
52. `topological quantum`
53. `adiabatic quantum`
54. `variational quantum`
55. `hybrid quantum`
56. `quantum neural network`
57. `qnn`
58. `quantum walk`
59. `quantum fourier transform`
60. `grover algorithm`
61. `shor algorithm`
62. `quantum key distribution`
63. `qkd`
64. `bell state`
65. `ghz state`
66. `bloch sphere`
67. `density matrix`
68. `quantum state`
69. `quantum measurement`
70. `quantum decoherence`
71. `quantum noise`

## Maintenance

Update `config/ingestion_config.json` first whenever the taxonomy changes, then
synchronize this document so the public repository description continues to
match the executable ingestion configuration.
