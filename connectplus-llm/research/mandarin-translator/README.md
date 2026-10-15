#	English	↔	Traditional	Mandarin	Translator
A	fine-tuned	neural	machine	translation	model	that	translates	between
English	and	Traditional	Mandarin	Chinese	in	both	directions.	Built	as
the	Chinese-language	component	of	a	multilingual	platform	for	senior
Chinese	speakers	in	Australia,	where	users	can	ask	everyday	questions
(for	example,	how	to	spot	a	scammer	or	how	to	safely	download	a	file)
and	get	answers	in	their	own	language.
No	external	translation	API	is	used.	The	model	is	fine-tuned	from
scratch	on	our	own	data	pipeline	and	runs	fully	offline	once	trained.
##	Approach
**Base	model:**	`facebook/nllb-200-distilled-600M`.	NLLB-200	already
recognises	`zho_Hant`	(Traditional	Chinese)	as	one	of	its	200
languages,	so	instead	of	training	two	separate	models	(English	to
Chinese	and	Chinese	to	English),	a	single	fine-tuned	model	can
translate	in	either	direction	by	switching	the	target-language	token.
**Data:**	[OPUS-100](https://huggingface.co/datasets/Helsinki-NLP/opus-100),
an	English-centric	parallel	corpus	covering	100	languages.	Its	Chinese
side	is	Simplified	script,	so	every	sentence	pair	is	converted	to
Traditional	Chinese	with	OpenCC	before	training,	since	the	platform
specifically	needs	Traditional	Mandarin.
**Training:**	each	parallel	pair	is	tokenised	in	both	directions
(English	to	Chinese	and	Chinese	to	English)	so	the	model	learns	to
translate	either	way.	Fine-tuning	uses	Hugging	Face's
`Seq2SeqTrainer`,	tracked	with	BLEU	on	a	held-out	validation	split.
Training	was	run	on	Google	Colab's	free	T4	GPU.
**Script	detection:**	a	separate	offline	module	checks	whether	input
text	is	Traditional	Chinese,	Simplified	Chinese,	or	not	Chinese	at
all,	using	Unicode	range	matching	plus	the	`hanzidentifier`	library.
This	lets	the	app	auto-detect	which	direction	to	translate	in,
instead	of	asking	the	user	to	specify.
##	Repository	structure
```
mandarin-translator/
├──	mandarin_translator.ipynb			#	Everything:	data	prep,	training,	evaluation,	detection,	inference
└──	requirements.txt
```
Kept	as	a	single	notebook	rather	than	split	into	separate	scripts,
since	the	whole	pipeline	(data,	training,	evaluation,	script
detection,	and	inference)	depends	on	the	same	tokenizer	and	model
objects	and	is	meant	to	be	run	top	to	bottom	in	one	Colab	session.
##	Usage
Open	`mandarin_translator.ipynb`	in	Google	Colab,	set	the	runtime	to
a	T4	GPU	(Runtime	>	Change	runtime	type),	and	run	the	cells	in	order:
1.	**Install	dependencies**
2.	**Mount	Google	Drive**	so	the	trained	model	persists	after	the
session	ends
3.	**Data	prep**	—	downloads	OPUS-100	(en-zh),	converts	the	Chinese
side	to	Traditional	script	with	OpenCC
4.	**Load	base	model	and	tokenizer**
5.	**Tokenize**	both	translation	directions
6.	**Train**	with	Hugging	Face's	`Seq2SeqTrainer`,	saving	the
checkpoint	to	Drive
7.	**Translation	helper**	—	quick	sanity	check	on	a	couple	of
sentences
8.	**Evaluation**	—	BLEU	score	on	the	validation	set,	both	directions
9.	**Script	detector**	—	offline	check	for	Traditional	vs	Simplified
vs	non-Chinese	input
10.	**Full	pipeline**	—	detector	+	trained	model	combined
11.	**Interactive	test**	—	type	sentences	in	and	get	live	translations
##	Notes	and	limitations-	The	Chinese	side	of	OPUS-100	is	Simplified;	it	is	converted	to
Traditional	with	OpenCC	rather	than	sourced	natively	in	Traditional
script,	so	translation	quality	on	Taiwan/Hong	Kong-specific
phrasing	may	be	weaker	than	on	general	Mandarin.-	The	`MAX_TRAIN`	variable	in	the	data	prep	cell	controls	how	much	of
the	roughly	1M-pair	dataset	is	used;	lower	it	for	a	faster	first	run.-	This	is	a	course	project	model,	not	a	production-grade	translator.
Before	using	it	for	anything	safety-critical	(for	example,	scam	or
fraud	guidance),	its	output	should	be	spot-checked	by	a	fluent
Traditional	Chinese	speaker.