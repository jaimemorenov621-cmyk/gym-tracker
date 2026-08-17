# Avisos de terceros

## Datos vectoriales del mapa muscular (`app/muscle_svg_data.py`)

Los paths SVG usados para dibujar el mapa muscular en el panel de resumen
(`Mis entrenamientos`) provienen de:

**react-muscle-highlighter**
https://github.com/soroojshehryar/react-muscle-highlighter

Licencia MIT, texto completo tal como aparece en el repositorio de origen:

```
MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

Solo se han copiado los datos de coordenadas de los paths (`assets/bodyFront.ts`,
`assets/bodyBack.ts`, `assets/bodyFemaleFront.ts`, `assets/bodyFemaleBack.ts`),
convertidos de TypeScript a un diccionario de Python — no se ha copiado ni
reutilizado el componente React en sí.
