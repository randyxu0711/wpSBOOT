# wpSBOOT Sever
* Web link : **[wpSBOOT](https://wpsboot.page.link/main)**
* Intro

    >We demonstrate that incorporating MSA induced uncertainty into bootstrap sampling can significantly increase correlation between clade correctness and its corresponding bootstrap value. Our procedure involves concatenating several alternative multiple sequence alignments of the same sequences, produced using different commonly used aligners. We then draw bootstrap replicates while favoring columns of the more unique aligner among the concatenated aligners. We named this concatenation and bootstrapping method, Weighted Partial Super Bootstrap (wpSBOOT).

* Enviroment configure: 

  ```
    pip install -r requirements.txt
  ```

* Notice

    >1. Name your *virtualenv* as venv ,otherwise ***test_server.sh need to change path***.
    >2. ***cleanUp.sh*** is used to empty your uploads ( for user uploads ) directory.

---

### Reference :
- see original paper : [Bioinformatics, btz082](https://doi.org/10.1093/bioinformatics/btz082)
- web page reference :[T-coffee](http://tcoffee.crg.cat/apps/tcoffee/do:regular)
- Guidance 
    [Setup server](https://lufficc.com/blog/how-to-serve-flask-applications-with-uwsgi-and-nginx-on-ubuntu)  
    [Additional](https://hackmd.io/@Xpz2MX78SomsO4mV3ejdqg/SyvmmBCfX?type=view#%E6%9E%B6%E7%AB%99%EF%BC%9AuWSGI)
