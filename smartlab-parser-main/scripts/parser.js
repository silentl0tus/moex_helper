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

async function fetchWithFallback(container){
    for (el of stocks){
        const url = `https://smart-lab.ru/q/${el}/f/y`
        const proxyUrl = 'https://api.codetabs.com/v1/proxy?quest=';
        const object = {table: [{"ticket": el, "report": {}}]}

        try{
            const result = await fetch(proxyUrl + url)
            const res = await result.text()
            const parser = new DOMParser()

            const doc = parser.parseFromString(res, "text/html")
            const table = doc.getElementsByClassName("simple-little-table financials")[0]
            const rows = table.rows;
            for (let i = 0; i < rows.length; i++){
                object.table[0].report[rows[i].cells[0].innerText.replace(/\s+/g, ' ').trim()] = {}
                for (let j = 3; j < rows[i].cells.length; j++)
                    if (j != 8){
                        object.table[0].report[rows[i].cells[0].innerText.replace(/\s+/g, ' ').trim()][rows[2].cells[j - 1].innerText.replace(/\s+/g, ' ').trim()] = rows[i].cells[j].innerText.replace(/\s+/g, ' ').trim()
                    }
            }
            const data = await fetch('http://localhost:3000/', {
                method: "POST",
                headers: {
                    'Content-type': 'application/json'
                },
                body: JSON.stringify(object)
            })
            const span = document.createElement('span')
            const a = document.createElement('a');
            span.textContent = `${el}: `
            a.href = `http://localhost:3000/files/${el}.json`;
            a.text = "cкачать | "
            a.download = `${el}.json`;
            document.body.appendChild(span);
            document.body.appendChild(a);
        }
        catch (err){
            console.error(err)
        }
    }
}