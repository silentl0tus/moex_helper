const stocks = [
    "GAZP", "SBER", "LKOH", "GMKN", "ROSN", "NVTK", "TATN", "MGNT", "PLZL", "ALRS",
    "POLY", "CHMF", "NLMK", "MTSS", "AFKS", "PHOR", "VTBR", "RUAL", "DSKY", "TCSG",
    "FIVE", "OZON", "YNDX", "TCSI", "QIWI", "MAIL", "MDMG", "LSRG", "UPRO", "FEES",
    "RTKM", "HYDR", "ENPG", "BANEP", "MSNG", "TGKA", "TGKB", "TGKN", "KZOS", "KZMS",
    "LSNG", "LSNGP", "MSRS", "MSTT", "NKNC", "NKNCP", "KRKN", "KRKNP", "KGKC", "KGKCP",
    "BSPB", "CBOM", "SFIN", "SBERP", "SNGS", "SNGSP", "TATNP", "TRNFP", "MOEX", "RSTI",
    "RSTIP", "AKRN", "BELU", "KMAZ", "KUBE", "LNZL", "LNZLP", "MAGN", "NMTP", "NSVZ",
    "PIKK", "RKKE", "SVAV", "UNAC", "UWGN", "WTCMP", "ABRD", "BISV", "BISVP", "DIAS",
    "DVEC", "DZRD", "DZRDP", "ELTZ", "ETLN", "GEMA", "GTSS", "IGST", "IGSTP", "KLSB",
    "KROT", "KROTP", "LPSB", "MRSB", "MSST", "MGNZ", "NAUK", "NKSH", "ODVA", "PRFN",
    "RBCM", "RDRB", "ROLO", "RTKZ", "SIBN", "SLEN", "STSB", "TASB", "TUZA", "UKUZ"
];
async function testPost() {
    for (let el of stocks){
        console.log(el)
    }
}

// Запускаем тест
testPost();