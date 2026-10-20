# Prior art: content plus sparse behaviour for item embeddings

Research for issue #9 (map: issue #8). Question: how do published systems build general-purpose item embeddings from content features when behavioural signal covers only part of the catalog? Covers training objectives, missing modalities, evaluation without a downstream task, and wine/food prior art.

Method and honesty note: every claim below was checked against the paper's own abstract page (arXiv, NeurIPS, Google Research) or, where stated, its full text. Statements marked "(my inference)" are not from the source. Full-text methods and results of several recommender papers (CLCRec, Content2Vec, CDL, LightFM, UniSRec, SMIL) were not read; only abstracts were, so details of their losses are not asserted here.

## Summary

- Prior art converges on one shape: a content encoder is the only path into the vector, and behaviour acts as a training signal (positives, regulariser, or reconstruction target) rather than as an input. Cold-start items then embed through content alone by construction.
- Four objective families exist: contrastive/mutual-information (CLCRec), hybrid reconstruction + collaborative (CDL), factorisation over feature embeddings (LightFM, Meta-Prod2Vec), and link prediction / two-tower with in-batch negatives (Content2Vec, Yi et al.).
- Missing behaviour is handled in training, not by imputation: dropout of the behavioural input (DropoutNet) or never feeding it (CLCRec, LightFM).
- There is no accepted intrinsic metric. The literature uses proxy tasks, human-labelled similarity sets, and label-free geometry diagnostics (alignment/uniformity, effective rank).
- Wine-specific prior art is thin and mostly text-based; evaluation there is weak or qualitative, except RecoBERT's sommelier-annotated set. No source named "wine2vec" was found.

## 1. Training objectives

### Contrastive / mutual information between content and behaviour

- CLCRec (Wei et al., ACM MM 2021) recasts cold-start item representation as maximising mutual information between item content and collaborative signals, derives a lower bound with two terms, and implements it as a contrastive framework. The authors report gains in both warm and cold start. [arXiv:2107.05315](https://arxiv.org/abs/2107.05315)
- SimCSE (Gao et al., EMNLP 2021) shows contrastive training makes an anisotropic text-embedding space more uniform and aligns positives; the unsupervised variant uses dropout noise as the only augmentation. Relevant to the French-text branch: a positive pair can be built with no labels. [arXiv:2104.08821](https://arxiv.org/abs/2104.08821)
- UniSRec (Hou et al., KDD 2022) encodes items from text only (whitening plus a mixture-of-experts adaptor) and pre-trains with two contrastive tasks using multi-domain negatives, so the item encoder is ID-free and transfers. [arXiv:2206.05941](https://arxiv.org/abs/2206.05941)

### Autoencoder / hybrid reconstruction

- Collaborative Deep Learning (Wang et al., 2014/2015) trains a deep representation of item content jointly with a collaborative filter on the ratings matrix, motivated by sparse ratings. [arXiv:1409.2944](https://arxiv.org/abs/1409.2944)

### Factorisation over feature embeddings

- LightFM (Kula, 2015) builds item representations as a sum of latent factors of content features. It beats pure CF and pure content when interactions are sparse or missing, and matches CF when data is plentiful. Feature embeddings also carry word-embedding-like semantics. [arXiv:1507.08439](https://arxiv.org/abs/1507.08439)
- Meta-Prod2Vec (Vasile et al., RecSys 2016) learns item embeddings from interaction sequences and uses item metadata as side information to regularise them. [arXiv:1607.07326](https://arxiv.org/abs/1607.07326)

### Hybrid / two-tower, link prediction

- Content2Vec (Nedelec, Smirnova, Vasile, 2017) builds a single product vector from modality-specific modules (text, image, categorical attributes, co-occurrence), fused at the end so each module trains separately. The objective is link prediction on co-purchased pairs. It is evaluated on cold-start and cross-category setups. [arXiv:1706.07625](https://arxiv.org/abs/1706.07625)
- Yi et al. (RecSys 2019) train two-tower models with in-batch negatives and show this introduces sampling bias that hurts under power-law item popularity; they correct it with a streaming frequency estimator. [Google Research](https://research.google/pubs/sampling-bias-corrected-neural-modeling-for-large-corpus-item-recommendations/)

### Attribute prediction

- Beer2Vec (Baillargeon and Garneau) is skip-gram-like: it predicts a beer's flavour tags from a beer embedding via softmax, with a shared beer/flavour space (k = 5, ~500k Untappd check-ins, 14.6k beers). Closest published analogue to "predict tasting traits from the item", but only standardised tags were used, not free-text reviews. [arXiv:2208.04223](https://arxiv.org/abs/2208.04223)

### Implications for this project (my inference)

- Pseudo-user author names are weak as user ids, so user-item collaborative objectives (CLCRec, CDL, DropoutNet) are not directly usable. Item-item signals that survive without user ids are: shared review text, shared employee pick lists, and shared attributes. Treat the "behaviour" signal as item-item co-occurrence (Meta-Prod2Vec, Content2Vec style) or as text targets, to be decided in the objective ticket.
- Tasting traits exist for ~25% of wines: attribute prediction with a masked loss (Beer2Vec style) fits, since the label is the target and never an input.

## 2. Handling missing modalities

- DropoutNet (Volkovs, Yu, Poutanen, NeurIPS 2017) trains "explicitly for cold start through dropout", so the same network handles warm items (collaborative input present) and cold items (input dropped). It can be layered on an existing latent model. [NeurIPS 2017](https://papers.nips.cc/paper/2017/hash/dbd22ba3bd0df8f385bdac3e9f8be207-Abstract.html)
- SMIL (Ma et al., AAAI 2021) studies training sets where up to ~90% of examples lack a modality, and reports Bayesian meta-learning beating autoencoder and GAN imputation baselines on its benchmarks. [arXiv:2103.05677](https://arxiv.org/abs/2103.05677)
- CLCRec, LightFM, UniSRec avoid the problem: the item vector is a function of content only, behaviour only shapes training (see section 1).
- Content2Vec fuses late, so a missing modality can be handled per module (my inference from the "train separately" design; not stated as a missing-data technique).
- Implication (my inference): with reviews on ~41% and picks on ~22% of groups, modality dropout during training is the documented pattern, and it also forces the vector not to depend on presence of reviews, which bears on the availability-skew concern in issue #8. Evidence that dropout removes the skew is not in these sources.

## 3. Evaluating a general-purpose embedding without a downstream task

- MTEB (Muennighoff et al.) evaluates text embeddings across 8 task types, 58 datasets, 112 languages, and finds no method wins everywhere; the lesson is to evaluate over a panel of tasks, not one. [arXiv:2210.07316](https://arxiv.org/abs/2210.07316)
- Alignment and uniformity (Wang and Isola, ICML 2020): two measurable geometric properties of contrastive embeddings that the authors show track downstream performance closely on vision and language data. [arXiv:2005.10242](https://arxiv.org/abs/2005.10242)
- RankMe (Garrido et al., ICML 2023): effective rank of the representations as a label-free quality criterion, used for hyperparameter selection with little loss versus label-based selection. Evidence is from image self-supervised learning; transfer to item embeddings is my inference. [arXiv:2210.02885](https://arxiv.org/abs/2210.02885)
- Cold-start protocol: Content2Vec and CLCRec both evaluate warm and cold item splits separately. [arXiv:1706.07625](https://arxiv.org/abs/1706.07625), [arXiv:2107.05315](https://arxiv.org/abs/2107.05315)
- Human-labelled similarity: RecoBERT (below) uses sommelier-annotated similar-wine lists (1,095 recommendations for ~100 seed wines), with MRR, mean percentile rank and HR@k. WineSensed collects pairwise human flavour-similarity rankings.

Implication (my inference): a proxy panel is the realistic design: (a) held-out attribute recovery (grape, region, colour, tasting traits) via probes, (b) a small hand-labelled similar-wine set, (c) geometry diagnostics (uniformity, effective rank), (d) cold versus warm split reporting, (e) a check that nearest-neighbour quality does not vary with review/pick coverage. Items (a)-(c) are drawn from the sources above; (e) is not from any source.

## 4. Wine and food prior art

- No paper or repository called "wine2vec" was found in searches. Do not cite it.
- RecoBERT (Malkiel et al., 2020): text-only item-to-item wine recommendation on ~120K Kaggle wine titles + expert reviews, no usage data or similarity labels needed for training; the authors release sommelier annotations. Inputs are a title (winery, year, wine name, grape) and a review. Reported on the 120K catalog with descriptions only: 10.4% HR@10, 21.0% MRR vs 4.5% / 11.6% for the best baseline; on the expert subset 65.4% HR@10, 91.7% MRR. [arXiv:2009.13292](https://arxiv.org/abs/2009.13292) (full text read via ar5iv)
- WineSensed / "Learning to Taste" (Bender et al., NeurIPS 2023 datasets track): 897k label images and 824k Vivino reviews, ~350k vintages with metadata (year, region, rating, alcohol, price, grapes). 256 participants produced >5,000 pairwise flavour distances; a concept-embedding method combining human judgements and automatic similarity outperformed separate embeddings on coarse classification (alcohol, country, grape, price, rating). [NeurIPS poster](https://neurips.cc/virtual/2023/poster/73572)
- WineGraph (Gawrysiak et al., 2024): extends FlavorGraph with wine; trains word2vec and TF-IDF on ~130k wine reviews to get 300-d aroma vectors plus 7 scalar values. Evaluation is largely qualitative (nearest/furthest items per taste) plus NMI on food-category clustering (0.358 with wine vs 0.309 without, at different epochs). Pairing rules were not validated against experts. [arXiv:2407.00107](https://arxiv.org/abs/2407.00107) (full text read via arXiv HTML)
- Beer2Vec: see section 1. Evaluation is almost entirely qualitative (three query beers, one homebrewer judge); sparse tags and rarely checked-in beers did poorly; free-text reviews were deliberately excluded. [arXiv:2208.04223](https://arxiv.org/abs/2208.04223)
- Flavor network (Ahn et al., Scientific Reports 2011): ingredients linked when they share flavour compounds; analyses >56,000 recipes. A compound-based, review-free notion of "what the food is", but needs chemistry data that SAQ lacks. Verified only through the search summary, not the paper page (publisher redirected), so treat details as unconfirmed. DOI [10.1038/srep00196](https://doi.org/10.1038/srep00196)
- MetricBERT (arXiv:2208.06610): the abstract page describes a video-game similarity dataset, not wine. A search snippet claiming a wine dataset was not confirmed; do not cite for wine.

Gaps relevant to this project: none of the above handle French text, structured SAQ fields, or partially missing behavioural signal; none provide a quantitative intrinsic evaluation beyond RecoBERT's annotated set.

## 5. Findings per downstream ticket

- Objective: content-only encoder with behaviour as a training signal (contrastive, CLCRec/Content2Vec style) and optionally masked attribute prediction (Beer2Vec style); modality dropout for reviews/picks.
- Evaluation: proxy panel plus cold/warm split; build a small hand-labelled similarity set modelled on RecoBERT's (about 100 seeds, about 10 labelled neighbours each). The `hand-review sample` already in the repo may seed it.
- Text and structured features: text-only item encoders transfer (UniSRec, RecoBERT); LightFM and Content2Vec show categorical attributes embed as learned feature vectors summed or fused with text. French handling is untested in all sources.

## Open questions the sources do not answer

- Whether any of these methods remove popularity/availability skew when reviews are present for a non-random subset (Yi et al. address popularity bias in negatives only).
- How well geometry diagnostics (uniformity, rank) predict quality for tabular+text item vectors.
- Performance of multilingual or French text encoders on SAQ-style descriptions.
