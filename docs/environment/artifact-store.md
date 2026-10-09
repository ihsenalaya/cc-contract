# Stockage du projet dans Azure

Le 9 octobre 2026, Terraform a créé les cinq ressources dédiées : groupe de
ressources `cc-contract-artifacts`, compte StorageV2 Hot LRS dans East US 2,
attribution du rôle d'écriture au compte utilisateur et conteneurs privés
`models` et `evidence`. Aucune VM ou GPU n'est incluse dans ce stockage.

L'accès public aux blobs et les clés partagées sont désactivés. L'accès utilise
Microsoft Entra ID, HTTPS et TLS 1.2. Les versions et les rétentions de suppression
de 30 jours sont activées. Ces ressources persistantes ne font pas partie de la
destruction d'une fenêtre GPU temporaire. Le code se trouve dans
[le module Terraform](../../infrastructure/azure/artifact-store/main.tf).

La création effective est consignée dans un état privé sous
`~/.local/state/cc-contract/artifact-store/`. Les identifiants d'accès, plans,
états et preuves originales ne sont pas publiés dans Git.

Le transfert initial par les outils Windows a échoué avec l'erreur WSL
`UtilAcceptVsock accept4 110`. Le transfert direct depuis Linux est implémenté
dans [azure-artifacts.py](../../scripts/azure-artifacts.py). Il nécessite une
connexion native avec [azure-storage-login.py](../../scripts/azure-storage-login.py),
qui emploie le client public officiel Azure CLI et conserve son cache avec
permissions privées. Une connexion à un autre compte est refusée.

Chaque bloc transféré comporte une empreinte MD5 contrôlée par Azure. Le fichier
complet est ensuite relu depuis Azure : son SHA-256 et sa longueur doivent
correspondre au fichier local. Le reçu n'est écrit qu'après cette vérification.
Une source locale ne peut être libérée sur la seule base d'une existence distante
ou d'une métadonnée. Les noms des blobs comprennent l'empreinte du contenu ;
un fichier existant ne peut pas être écrasé lors de la validation finale.

Les preuves Kind, les traces CPU et l'archive de la première H100 sont copiées
dans une archive dédiée, avec index et vérification de chaque membre avant
transfert. Les clés SSH et les caches d'authentification ne sont pas sélectionnés.
Les preuves originales restent conservées localement.

Les quatorze fichiers de modèle et de corpus sont sauvegardés :
15 242 896 869 octets, tous relus depuis Azure et vérifiés par SHA-256 et longueur.
Les quatre copies locales des poids ont été supprimées après nouvelle
vérification des sources : 15 231 271 888 octets retirés du cache Linux.
Cela ne constitue pas une mesure supplémentaire d’espace Windows récupéré.
Les petits fichiers de configuration et les preuves originales restent conservés.
La préparation du prochain pilote doit maintenant exploiter les copies Azure
vérifiées ; le transport actuel du pilote exige encore les sources locales et
doit être adapté. Aucun nouveau pilote n'est déclaré prêt ou exécuté sur cette base.

Le cluster Kind du projet, ses copies d'images et le cache de compilation Docker
ont été retirés après qualification et publication. La taille physique du VHD
Docker Windows ne diminue pas automatiquement avec ces suppressions. Le script
[compact-docker-disk.ps1](../../scripts/compact-docker-disk.ps1) sélectionne
uniquement le VHD Docker existant, exige Docker Desktop arrêté et un accès
exclusif au fichier, puis demande sa compaction sans supprimer ses volumes.
Windows exige une console administrateur. L'exécution réelle et la récupération
d'espace sont vérifiées ci-dessous.

## Compaction Windows vérifiée

Après arrêt de Docker Desktop, terminaison de la seule distribution
`docker-desktop` et détachement du seul VHD Docker, la compaction DiskPart a
réussi. Le fichier est passé de 80,74 à 43,93 GiB : 36,81 GiB récupérés.
Windows affichait 38,91 GiB libres après l’opération. La taille du fichier et
l’espace libre ont aussi été contrôlés depuis WSL. Ubuntu et le transfert Azure
sont restés actifs ; aucun volume existant n’a été supprimé par la compaction.
Le format UTF-16 du fichier de commandes initial avait provoqué un échec ;
le script utilise maintenant le texte Windows sans BOM ni octets NUL.
