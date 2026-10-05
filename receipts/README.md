# Receipts

Fingerprints, time stamps and sealed score files for the results in the main README. The README's "Receipts" section explains how to check them.

- Each `*-SHA256.txt` is a list of SHA-256 fingerprints, one file per line. Its `.tsq` and `.tsr` are the FreeTSA time-stamp request and reply, and its `.ots` is the OpenTimestamps proof, where there is one.
- The files a list names are not all here. Answer files hold the exam's text, which stays unpublished until people have rated the items. The score files (`*/results/*.json`) are here and match their lists.
- Nothing here is edited after sealing. A line ending changed in a hash list would break its stamp, so `.gitattributes` keeps these files byte for byte.
