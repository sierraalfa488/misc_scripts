import re
import pdfreader

pdfFileObj = open('BIZBASH ALL PLANNERS.pdf','rb')
outfile_text = 'First Name,Last Name,Email Address\n'
viewer = pdfreader.SimplePDFViewer(pdfFileObj)
delegates = list()
counter = 1


while True:
    try:
        viewer.navigate(counter)
        viewer.render()
        text_list = viewer.canvas.strings
        pdf_text = ' '.join(text_list)
        _delegates = pdf_text.split('Delegate:')
        for _delegate in _delegates:
            delegates.append(_delegate)
        counter += 1
    except pdfreader.viewer.pdfviewer.PageDoesNotExist:
        break


for i in delegates:
    name = re.search(r"^.*T itle", i)
    email = re.search(r"\(.*\)", i)
    if name and email:
        name = name.group().replace('T itle', '').replace(' ', '')
        email = email.group()
        email = re.sub(r"\).*", '', email)
        email = email.replace('mailto:', '')
        email = email.replace('(', '')
        email = email.replace(' ', '')
        first_name = name.split(',')[1]
        last_name = name.split(',')[0]
        outfile_text += f'{first_name.capitalize()},{last_name.capitalize()},{email.lower()}\n'

with open('output.csv', 'w+') as f:
    f.write(outfile_text)
