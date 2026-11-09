# Author: gorcoding
# Built-in lexicons. Topic words = "words of meaning"; BOT_WORDS = phrases typical of spam/engagement bots.
TOPICS = {
 "politics": "politics political politician politicians government regime parliament congress senate democrat republican liberal conservative leftist nationalist populist election elections vote voting ballot rigged campaign policy minister president",
 "regions": "europe european eu brussels america american usa india indian pakistan pakistani china chinese russia russian ukraine israel palestine gaza iran turkey africa asia britain england france germany sweden canada australia",
 "religion": "muslim muslims islam islamic islamist hindu hindus hindutva christian christians christianity jew jews jewish sikh buddhist church mosque temple quran bible halal",
 "migration": "immigrant immigrants immigration migrant migrants refugee refugees asylum border borders deport deportation illegal invasion visa citizenship",
 "conflict": "war army military soldier soldiers terror terrorist terrorism attack attacks bomb missile genocide massacre killed violence riot protest",
 "media": "media news fake propaganda lies journalist journalists narrative censorship censored truth exposed leaked",
 "economy": "economy inflation tax taxes jobs unemployment crypto bitcoin ethereum token airdrop nft scam stock market billionaire elite",
 "society": "woke lgbt feminism feminist gender trans abortion crime police racism racist culture tradition family",
 "health": "vaccine vaccines covid pandemic virus lockdown",
 "tech": "chatgpt elon musk twitter google tiktok",
}
BOT_WORDS = ["follow back","followback","follow for follow","f4f","retweet","rt if","giveaway","airdrop","dm me","dm for",
 "link in bio","click here","join now","breaking:","breaking news","wake up","share this","must watch","100% real","guaranteed",
 "earn $","earn money","passive income","limited time","free crypto","whitelist","pump","to the moon","like and retweet",
 "tag a friend","mainstream media","they don't want you to know","spread the word","sign the petition","retweet this"]
AUTO_CLIENTS = ["ifttt","buffer","hootsuite","dlvr.it","zapier","python","bot","twittbot","sprout","socialoomph","automate",
 "botsincommon","crowdfire","publer","make.com","n8n","tweepy","requests","tweetcaster auto"]
STOP = set("""the and for are but not you all any can had her was one our out has have this that with from they will would there their what
about which when your said each she how its who him his them then than these those been being were into over also just like more most
some such only other very much many get got can't cant don't dont didn't did does doing done going gone make made see saw say says
because while where after before again here still even ever never always too now off own same both few why let let's lets yes
http https www com amp via per out our ours you're youre i'm im it's its i've ive we're were they're theyre should could may might
must shall really thing things people one two new old good great back way want need know think look come take time day today
https cant wont isnt arent wasnt aren't isn't wasn't won't""".split())
