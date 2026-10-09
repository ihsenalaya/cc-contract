# Bilan technique du 9 octobre 2026

Le logiciel et les vérifications locales ont avancé. Les expériences scientifiques
complètes E0–E8 ne sont pas terminées. Aucun nouveau défaut GPU confirmé ni
avantage de B4 sur les baselines n'est établi.

## Livré et vérifié

- Première fenêtre H100 : attestation hôte partiellement revue, CC ON/PRODUCTION,
  54 observations CUDA entières recalculées, désallocation puis destruction des
  13 ressources temporaires. La qualification complète avait échoué sur
  l'absence de PyTorch dans l'hôte ; cet échec reste conservé.
- 50 tests de source passent, avec vérifications des erreurs de qualification,
  de la libération, des preuves modifiées, des métadonnées et des credentials RAM.
- Générateurs bornés T01–T08, validation conservatrice avant CUDA, génération
  physique séparée dans le worker natif, recherche B1–B4 et trois ablations,
  réduction, reprise de campagnes et analyse avec unités indépendantes.
- Image native construite localement depuis un commit figé : 96 cas et
  252 observations en référence CPU, sur chacun des deux workers Kind. Un autre
  contrôle recalcule les observations depuis les traces détaillées. L'absence
  de GPU est explicitement rejetée.
- Image PyTorch construite localement depuis une base officielle épinglée :
  18 résultats de composants par worker Kind et une petite fixture Transformers
  aléatoire. Cette fixture n'exécute pas Qwen 7B.
- Douze fichiers Qwen2.5-7B-Instruct téléchargés et vérifiés ; 24 textes publics
  synthétiques, huit à chacune des longueurs 32, 128 et 512 tokens, avec
  continuations imposées et empreinte figée.
- Préparation locale d'un flux tar déterministe de 15 242 915 840 octets,
  empreinte `84266aeb8e14a4e27ecc378300e393684fb9ec96d3876f812646668ccddcd1dc`.
  Ce transport évite une deuxième copie des poids sur disque. Le producteur
  et l'invité vérifient le flux transféré ; les sources sont revérifiées avant
  tout provisionnement.

Les preuves et limites sont référencées dans le
[manifeste local](../../results/manifests/pilot-local-qualification.json),
le [premier résultat GPU](first-gpu-result.md) et
l'[état versionné](../../experiments/status.json).

## État des expériences

| Expérience | État réel | Travail restant |
|---|---|---|
| E0 | H100 partiellement qualifiée ; infra locale validée | Nouvelle qualification avec PyTorch, revue indépendante de preuve GPU, recréation H100 et branche d'expiration réelle |
| E1 | Oracles entiers et références flottantes vérifiés localement | Calibration et variabilité sur GPU ; gel des oracles |
| E2 | T01–T08 validés en référence CPU native | Exécution CUDA réelle et décision de support mapped/graphes, puis évaluation réservée |
| E3 | H08/H09 documentés, causes non confirmées | Logs et configurations originaux, reproductions isolées vérifiées |
| E4 | Algorithmes et chaîne CPU validés | Gel du protocole, budget approuvé, campagnes GPU complètes |
| E5 | Ablations et planning implémentés | Même qualification et campagnes GPU complètes |
| E6 | Réducteurs vérifiés localement | Anomalie réelle reproduite, puis essais GPU appariés ; sinon non-applicabilité motivée |
| E7 | Image CPU, poids et corpus prêts | Composants GPU, 24 inférences Qwen appariées, revue des traces et métadonnées |
| E8 | Harnais CPU de mesure et contrôle de correction vérifié | Anomalie caractérisée et intervention correcte, puis mesures GPU appariées |

Les quatorze campagnes CPU de développement d'une seconde vérifient le pipeline.
Elles ne remplacent pas les campagnes GPU de dix minutes. Le planning E4/E5
conserve 20 blocs indépendants, sept méthodes et 600 secondes par méthode,
soit 140 campagnes et 23 h 20 de calcul, hors installation et qualification.

L'infrastructure Azure actuelle automatise une VM temporaire avec Docker,
qualification, collecte, libération et expiration indépendante. L'intégration
Azure kubeadm/composants GPU n'est pas implémentée ou qualifiée. Elle reste à
préparer si le périmètre Kubernetes Azure est retenu ; les essais Kind ne la
valident pas. La reproductibilité H100 complète n'est pas encore démontrée.

## Prochaine fenêtre proposée

Une H100, deux heures maximum et autorisation proposée de 20 USD pour la
qualification native étendue, les composants flottants et les 24 prompts Qwen.
Les longues campagnes comparatives sont exclues. Le tarif public interrogé donne
13,96 USD de calcul pour deux heures ; la proposition inclut une marge pour les
autres ressources, sans garantir une facture plafonnée.
Voir la [proposition chiffrée](../../results/manifests/next-pilot-cost-proposal.json).

Le paquet définitif doit relier les digests publiés, les preuves Kind, le modèle,
le corpus et le script de qualification au plan Terraform soumis à approbation.
L'absence de réponse n'autorise aucune allocation. Après collecte vérifiée,
la VM est immédiatement désallouée et les ressources temporaires détruites.
La branche d'expiration indépendante couvre les défaillances du poste client,
avec les délais propres au contrôle Azure.

L'espace physique Windows reste faible après chargement des deux copies PyTorch.
Le flux sans copie supplémentaire permet de poursuivre la préparation locale.
Les erreurs intermittentes d'interop Windows et les tentatives de publication
échouées sont conservées dans le registre d'incidents ; la publication utilise
des credentials temporaires en RAM pour éviter ce relais.
