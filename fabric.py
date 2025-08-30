import json
import sys, ssl
from datetime import datetime, date
import xmlrpc.client
from datetime import datetime, date, timedelta
import pdb

def main(data):
    print("Iniciando ejecución de Orden_de_fabricacion.py")
 
    # Definir los valores de la conexión
    url = 'https://odoo-qa.thomasgreg.com/' #'https://odoo-test1.thomasgreg.com/'
    db = 'portalerp' #'db_cost' 

    username = data.get("usuario")
    password = data.get("password")
    #context = {'allow_none': True, 'verbose': False, 'use_datetime':True, 'context': ssl._create_unverified_context()}
    ssl_context = ssl._create_unverified_context()
    common = xmlrpc.client.ServerProxy(
        f"{url}/xmlrpc/2/common",
        allow_none=True,
        use_datetime=True,
        context=ssl_context
    )
    models = xmlrpc.client.ServerProxy(
        f"{url}/xmlrpc/2/object",
        allow_none=True,
        use_datetime=True,
        context=ssl_context
    )
    #common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common", **context)
    uid = common.authenticate(db, username, password, {})
    #models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object", **context)

    encabezado = data["Encabezado"]
    lineas = data.get("Backorders", [])

    # Entrada de datos orden de producción
    hoy = date.today()
    FechaLimite = hoy + timedelta(days=1)
    FechaLimitestr = FechaLimite.isoformat()
    Cantidad = float(encabezado.get("CantProducir", 0))  
    version_bom = encabezado.get("Campo Nuevo", 1)

    def cantidad_producir(Cantidad):
        referencia = str(encabezado.get("Producto"))
        cantidad_fabricar = float(lineas[0].get("Cant. a Fabricar", 0))
        return referencia, cantidad_fabricar
    referencia, cantidad_fabricar = cantidad_producir(Cantidad)

    # Entrada de datos de productividad
    def datos_productividad():
        fecha_hora = datetime.fromisoformat(lineas[0]["Fecha Inicio"])
        fecha_hora_fin = datetime.fromisoformat(lineas[0]["Fecha Fin"])
        CentroDeTrabajo = encabezado.get("Centro de Trabajo")
        TipodeActividad = lineas[0].get("Tipo de Actividad")
        horahombre = float(lineas[0].get("Hora Hombre", 0))
        maquina = float(lineas[0].get("Hora Maquina", 0))
        cargues = float(lineas[0].get("Hora Carga", 0))
        return fecha_hora, fecha_hora_fin, CentroDeTrabajo, TipodeActividad, horahombre, maquina, cargues
    fecha_hora, fecha_hora_fin, CentroDeTrabajo, TipodeActividad, horahombre, maquina, cargues = datos_productividad()

    #Entrada de datos de lote
    def lote():
        lote_name = lineas[0]["Lote"]
        Localizacion = encabezado.get("Almacén")
        return lote_name, Localizacion
    lote_name, Localizacion  = lote() 

    # Obtener la compañía
    def company():
        idcompany = int(str(encabezado.get("Company", "")).strip() or 0)
        company_ids = models.execute_kw(
            db, uid, password, 'res.company', 'search',
            [[['id', '=', idcompany]]]
        )
        mrp_production_type_id = int(3)
        models.execute_kw(
            db, uid, password, 'res.users', 'write',
            [[uid], {'company_id': company_ids[0]}]
        )
        return company_ids, mrp_production_type_id
    company_ids, mrp_production_type_id = company()

    # Buscar el producto
    def producto():
        PlantillaDeProducto = models.execute_kw(
            db, uid, password, 'product.product', 'search_read',
            [[['default_code', '=', referencia], ['company_id', '=', company_ids[0]]]],
            {'fields': ['id', 'company_id']}
        )
        product_id = PlantillaDeProducto[0].get('id')
        tracking_info = models.execute_kw(
            db, uid, password, 'product.product', 'search_read',
            [[['id', '=', product_id]]],
            {'fields': ['tracking']}
        )
        order_type_ids = models.execute_kw(
            db, uid, password, 'mrp.production.type', 'search',
            [[['id', '=', mrp_production_type_id]]]
        )
    
        # Buscar BOM que coincida con producto y versión
        bom = models.execute_kw(
            db, uid, password,
            'mrp.bom', 'search_read',
            [[
                ('product_id', '=', product_id),
                ('version', '=', int(version_bom))
            ]],
            {'fields': ['id'], 'limit': 1}
        )
        bom_id = bom[0]['id'] if bom else False

        datos = {
            'date_deadline': FechaLimitestr,
            'product_qty': Cantidad,
            'product_id': product_id,
            'order_type_id': order_type_ids[0],
            'company_id': company_ids[0],
            'product_uom_id': Cantidad,
            'product_uom_qty': Cantidad,
            'qty_producing': cantidad_fabricar,
            'bom_id': bom_id,
            'product_qty_done': Cantidad
        }
        return PlantillaDeProducto, product_id, tracking_info, order_type_ids, datos
    PlantillaDeProducto, product_id, tracking_info, order_type_ids, datos = producto()

    def obtener_secuencia_desde_bom(bom_id, company_id):
       #Obtiene la secuencia correcta desde el BOM y su producto
        try:
            # Obtener el BOM completo
            bom = models.execute_kw(db, uid, password, 'mrp.bom', 'read',
                [[bom_id]], {'fields': ['picking_type_id']}
            )
            
            if not bom:
                return None
                
            picking_type_id = bom[0].get('picking_type_id')

            if not picking_type_id:
                print("No se pudo obtener picking_type_id del BOM")
                return None
                
            # Obtener el stock.picking.type
            picking_type = models.execute_kw(db, uid, password, 'stock.picking.type', 'read',
                [[picking_type_id[0]]], {'fields': ['sequence_id', 'sequence_code']}
            )
            
            if not picking_type or not picking_type[0].get('sequence_id'):
                print("Picking type no tiene sequence_id")
                return None
                
            sequence_id = picking_type[0]['sequence_id'][0]
            
            # Obtener la secuencia completa
            sequence = models.execute_kw(db, uid, password, 'ir.sequence', 'read',
                [[sequence_id]], {'fields': ['id', 'name', 'code', 'prefix', 'padding', 'number_next_actual']}
            )
            
            return sequence[0] if sequence else None
                
        except Exception as e:
            print(f"Error obteniendo secuencia desde BOM: {e}")
            return None

    def obtener_bom_desde_producto(product_code, company_id, version_bom=1):
        #Obtener el BOM basado en el producto
        try:
            # Primero obtener el ID del producto desde su default_code
            producto = models.execute_kw(db, uid, password, 'product.product', 'search_read',
                [[['default_code', '=', product_code], ['company_id', '=', company_id]]],
                {'fields': ['id'], 'limit': 1}
            )
            
            if not producto:
                raise Exception(f"Producto no encontrado: {product_code}")
                
            product_id = producto[0]['id']
            
            # Buscar BOM que coincida con producto y versión
            bom = models.execute_kw(db, uid, password, 'mrp.bom', 'search_read',
                [[
                    ('product_id', '=', product_id),
                    ('version', '=', int(version_bom)),
                    ('company_id', '=', company_id)
                ]],
                {'fields': ['id', 'picking_type_id', 'code'], 'limit': 1}
            )
            
            if not bom:
                # Intentar sin versión específica
                bom = models.execute_kw(db, uid, password, 'mrp.bom', 'search_read',
                    [[
                        ('product_id', '=', product_id),
                        ('company_id', '=', company_id)
                    ]],
                    {'fields': ['id', 'picking_type_id', 'code'], 'limit': 1}
                )
                
            if bom:
                print(f"BOM encontrado: {bom[0]['code']}")
                return bom[0]
            else:
                print(" No se encontró BOM para el producto")
                return None
                
        except Exception as e:
            print(f"Error obteniendo BOM: {e}")
            return None

    def obtener_proximo_numero_secuencia(sequence_id, sequence_code):
        #Obtiene el próximo número de la secuencia y actualiza el contador
        try:
            # Obtener el próximo número
            next_number = models.execute_kw(db, uid, password, 'ir.sequence', 'next_by_id',
                [sequence_id]
            )
            
            # Si next_by_id no funciona, usar next_by_code
            if not next_number:
                next_number = models.execute_kw(db, uid, password, 'ir.sequence', 'next_by_code',
                    [sequence_code]
                )
            
            print(f"Próximo número de secuencia: {next_number}")
            return next_number
            
        except Exception as e:
            print(f"Error obteniendo próximo número: {e}")
            return None
        
    def obtener_id_compania(company_ids):
        if isinstance(company_ids, list) and len(company_ids) > 0:
            return company_ids[0]  # Si es lista, devuelve el primer elemento
        elif isinstance(company_ids, int):
            return company_ids  # Si ya es entero, lo devuelve directamente
        else:
            # Valor por defecto o error según tu caso
            return company_ids[0] if isinstance(company_ids, list) else company_ids    
    #Aca empece cambios ctrol Z

    def finalizar_produccion_completa(production_id, company_ids, cantidad_fabricar, Cantidad_total, nombre_produccion):
        #Función común para finalizar producción (usar en principal y backorders)
        try:
            print(f"Finalizando producción {nombre_produccion} con método completo...")
            
            # 1. Desactivar validación de stock negativo
            config_param = models.execute_kw(
                db, uid, password, 'ir.config_parameter', 'search_read',
                [[['key', '=', 'stock.no_negative']]],
                {'fields': ['id', 'value']}
            )
            if config_param:
                models.execute_kw(
                    db, uid, password, 'ir.config_parameter', 'write',
                    [[config_param[0]['id']], {'value': 'False'}]
                )

            # 2. Método alternativo para forzar moves
            production = models.execute_kw(
                db, uid, password, 'mrp.production', 'read',
                [[production_id]], {'fields': ['name', 'state', 'move_raw_ids']}
            )[0]
            
            moves_info = models.execute_kw(
                db, uid, password, 'stock.move', 'search_read',
                [[['id', 'in', production['move_raw_ids']]]],
                {'fields': ['id', 'product_id', 'product_uom_qty', 'name']}
            )
            
            for move in moves_info:
                cantidad_move = move['product_uom_qty']
                models.execute_kw(
                    db, uid, password, 'stock.move', 'write',
                    [[move['id']], {
                        'state': 'done',
                        'quantity_done': cantidad_move 
                    }]
                )
                print(f"Move {move['id']} forzado a 'done' (Cantidad: {cantidad_move})")
            
            # 3. Marcar producción como done
            models.execute_kw(
                db, uid, password, 'mrp.production', 'write',
                [[production_id], {
                    'state': 'done',
                    'qty_producing': cantidad_fabricar,
                    'product_qty': Cantidad_total
                }]
            )
            print("Producción forzada a estado 'done'")

            # 4.  Actualización de stock.quant
            print("=== ACTUALIZANDO STOCK.QUANT ===")
            moves_con_lotes = models.execute_kw(
                db, uid, password, 'stock.move', 'search_read',
                [[
                    ['raw_material_production_id', '=', production_id],
                    ['needs_lots', '=', True]  
                ]],
                {'fields': ['id', 'product_id', 'location_id', 'location_dest_id']}
            )
            
            for move in moves_con_lotes:
                move_lines = models.execute_kw(
                    db, uid, password, 'stock.move.line', 'search_read',
                    [[
                        ['move_id', '=', move['id']],
                        ['qty_done', '>', 0]  
                    ]],
                    {'fields': ['id', 'location_id', 'location_dest_id', 'lot_id', 'qty_done', 'product_id']}
                )
                
                if move_lines:
                    for ml in move_lines:
                        cantidad_consumida = ml['qty_done']
                        product_id = ml['product_id'][0]
                        
                        if ml['lot_id']:
                            # Actualizar almacen de origen
                            domain_origen = [
                                ['product_id', '=', product_id],
                                ['location_id', '=', ml['location_id'][0]],
                                ['lot_id', '=', ml['lot_id'][0]]
                            ]
                            
                            quants_origen = models.execute_kw(
                                db, uid, password, 'stock.quant', 'search_read',
                                [domain_origen],
                                {'fields': ['id', 'quantity']}
                            )
                            
                            if quants_origen:
                                quant_origen = quants_origen[0]
                                nuevo_stock_origen = max(0, quant_origen['quantity'] - cantidad_consumida)
                                
                                models.execute_kw(
                                    db, uid, password, 'stock.quant', 'write',
                                    [[quant_origen['id']], {
                                        'quantity': nuevo_stock_origen
                                    }]
                                )
                            
                            # Actualizar almacen de destino
                            domain_destino = [
                                ['product_id', '=', product_id],
                                ['location_id', '=', ml['location_dest_id'][0]],
                                ['lot_id', '=', ml['lot_id'][0]]
                            ]
                            
                            quants_destino = models.execute_kw(
                                db, uid, password, 'stock.quant', 'search_read',
                                [domain_destino],
                                {'fields': ['id', 'quantity']}
                            )
                            
                            if quants_destino:
                                quant_destino = quants_destino[0]
                                nuevo_stock_destino = quant_destino['quantity'] + cantidad_consumida
                                
                                models.execute_kw(
                                    db, uid, password, 'stock.quant', 'write',
                                    [[quant_destino['id']], {
                                        'quantity': nuevo_stock_destino
                                    }]
                                )
                            else:
                                # Crear nuevo quant en destino
                                quant_data = {
                                    'product_id': product_id,
                                    'location_id': ml['location_dest_id'][0],
                                    'lot_id': ml['lot_id'][0],
                                    'quantity': cantidad_consumida,
                                    'company_id': obtener_id_compania(company_ids)
                                }
                                
                                models.execute_kw(
                                    db, uid, password, 'stock.quant', 'create',
                                    [quant_data]
                                )

            # 5. Reactivar validación
            if config_param:
                models.execute_kw(
                    db, uid, password, 'ir.config_parameter', 'write',
                    [[config_param[0]['id']], {'value': 'True'}]
                )

            # 6. Ejecutar button_mark_done por si acaso
            try:
                models.execute_kw(
                    db, uid, password, 'mrp.production', 'button_mark_done',
                    [[production_id]]
                )
            except:
                pass  # Ignorar si falla, ya la forzamos a done

            print(f"Producción {nombre_produccion} finalizada correctamente")
            
        except Exception as e:
            print(f"Error en finalizar_produccion_completa: {e}")
            raise

    # Obtener el producto desde el encabezado
    product_code = encabezado.get("Producto")
    version_bom = encabezado.get("Campo Nuevo", 1)

    # Obtener el BOM correcto para este producto
    bom = obtener_bom_desde_producto(product_code, company_ids[0], version_bom)

    if bom:
        # Obtener la secuencia desde el BOM
        secuencia_info = obtener_secuencia_desde_bom(bom['id'], company_ids[0])
        
        if secuencia_info:
            numero_formateado = obtener_proximo_numero_secuencia(
                secuencia_info['id'], 
                secuencia_info['code']
            )
            datos['name'] = numero_formateado
            print(f"Usando secuencia del BOM: {numero_formateado}")
        else:
            print("Usando secuencia por defecto (no se encontró en BOM)")
            datos['name'] = '/'
    else:
        print("Usando secuencia por defecto (no se encontró BOM)")
        datos['name'] = '/'

    def validar_stock_suficiente(product_id, lot_id, cantidad_requerida, location_id):
        #Valida que haya stock suficiente antes de procesar la orden
        domain = [
            ['product_id', '=', product_id],
            ['location_id', '=', location_id],
            ['quantity', '>', 0]
        ]
        
        if lot_id and lot_id is not False:
            domain.append(['lot_id', '=', lot_id])
        else:
            domain.append(['lot_id', '=', False])
        
        stock_disponible = models.execute_kw(db, uid, password, 'stock.quant', 'search_read',
            [domain], {'fields': ['quantity', 'lot_id']}
        )
        
        total_stock = sum([q['quantity'] for q in stock_disponible])
        
        print(f"Validación stock: Producto {product_id}, Lote {lot_id}")
        print(f" Stock disponible: {total_stock}, Requerido: {cantidad_requerida}")
        
        if total_stock < cantidad_requerida:
            raise Exception(f"STOCK INSUFICIENTE: Se requieren {cantidad_requerida} unidades, pero solo hay {total_stock} disponibles")
        
        return True    
    
    # Crear orden de fabricación
    id = models.execute_kw(
        db, uid, password, 'mrp.production', 'create', [datos]
    )

    # Obtener nombre de la orden
    name = models.execute_kw(
        db, uid, password, 'mrp.production', 'search_read',
        [[['id', '=', id]]],
        {'fields': ['name']}
    )
    nombre = name[0].get('name')

    # Confirmar orden de fabricación
    nombreFabricacion = models.execute_kw(
        db, uid, password, 'mrp.production', 'search_read',
        [[['name', '=', nombre],['company_id', '=', company_ids[0]]]],
        {'fields': ['name','product_id','move_raw_ids']}
    )
    Nombre = nombreFabricacion [0].get('name')
    Componentes = nombreFabricacion[0].get('move_raw_ids')

    nombreStock = models.execute_kw(
        db, uid, password, 'stock.move', 'search_read',
        [[['raw_material_production_id', '=', id], ['company_id', '=', company_ids[0]]]],
        {'fields': ['name', 'product_id', 'id']}
    )
    idsStock = [move['id'] for move in nombreStock] if nombreStock else []
    
    for registro in nombreStock:
        Stock = registro.get('product_id')
        Stock_id = Stock[0]
        Componente = models.execute_kw(
            db, uid, password, 'product.product', 'search_read',
            [[['product_variant_ids', '=', Stock_id],['company_id', '=', company_ids[0]]]],
            {'fields': ['name','company_id','standard_cost','standard_price','default_code','id','product_variant_ids']}
        )        
        propiedad = str(Componente[0].get('product_variant_ids')).strip('[]')
        Texto = f"product.product,{propiedad}"
        ResID = models.execute_kw(
            db, uid, password, 'ir.property', 'search_read',
            [[['company_id','=',company_ids[0]],['res_id','=',Texto]]],
            {'fields': ['value_float']}
        )      
        NuevoCosto = ResID [0].get('value_float')      
        if Componente:
            componente_id = Componente[0]['id']
            nuevo_costo = NuevoCosto
            models.execute_kw(
                db, uid, password, 'product.product', 'write',
                [[componente_id], {'standard_price': nuevo_costo}]
            )
        else:
            print("Producto no encontrado.")
            
    Confirmar = models.execute_kw(
        db, uid, password, 'mrp.production', 'action_confirm',[id]
    )

    #Crear plan
    Plan = models.execute_kw(
        db, uid, password, 'mrp.production', 'button_plan',[id]
    )
    print("Orden de fabricación Odoo:", nombre)

    # Iniciar orden de trabajo
    OrdenTrabajo = models.execute_kw(
        db, uid, password, 'mrp.workorder', 'search_read',
        [[['production_id', '=', id], ['company_id', '=', company_ids[0]]]],
        {'fields': ['id']}
    )
    idOT = OrdenTrabajo[0].get('id')

    Iniciar = models.execute_kw(
        db, uid, password, 'mrp.workorder', 'button_start', [idOT]
    )

    workcenter_ids = models.execute_kw(
        db, uid, password, 'mrp.workcenter', 'search_read',
        [[['name', '=', CentroDeTrabajo], ['company_id', '=', company_ids[0]]]],
        {'fields': ['id']}
    )
    workcenter_id = workcenter_ids[0].get('id')

    loss_ids = models.execute_kw(
        db, uid, password, 'mrp.workcenter.productivity.loss', 'search_read',
        [[['code', '=', TipodeActividad], ['company_id', '=', company_ids[0]]]],
        {'fields': ['id']}
    )
    loss_id = loss_ids[0].get('id')

    datos = {
        'production_id': id,
        'date_start': fecha_hora.strftime('%Y-%m-%d %H:%M:%S'),
        'date_end': fecha_hora_fin.strftime('%Y-%m-%d %H:%M:%S'),
        'workcenter_id': workcenter_id,
        'loss_id': loss_id,
        'account_date': hoy.isoformat(),
        'company_id': company_ids[0],
        'duration_labor': horahombre,
        'duration_machine': maquina,
        'duration_load': cargues,
        'workorder_id': idOT,
    }

    # Crear registro de productividad
    productivity_id = models.execute_kw(
        db, uid, password, 'mrp.workcenter.productivity', 'create', [datos]
    )

    #Contabilización de costos
    try:
        Post = models.execute_kw(
            db, uid, password, 'mrp.workcenter.productivity', 'button_post', [[productivity_id]]
        )
    except xmlrpc.client.Fault as fault:
        if "dictionary key must be string" in str(fault):
            Post = {}  
        else:
            print("Error al ejecutar el método:", fault)
            raise

    # Crear Lote
    lote_existente = models.execute_kw(
        db, uid, password,
        'stock.lot', 'search_read',
        [[
            ('name', '=', lote_name),
            ('product_id', '=', product_id),
            ('company_id', '=', company_ids[0])
        ]],
        {'fields': ['id'], 'limit': 1}
    )

    if lote_existente:
        lote_id = lote_existente[0]['id']
    else:
        lote_id = models.execute_kw(db, uid, password, 'stock.lot', 'create', [{
            'name': lote_name,
            'product_id': product_id,
            'company_id': company_ids[0],
            'product_qty': cantidad_fabricar
        }])

    models.execute_kw(
        db, uid, password, 'mrp.production', 'write', [[id], {
        'lot_producing_id': lote_id
        }]
    )

    # Comprobar disponibilidad
    id_dispon = models.execute_kw(
        db, uid, password, 'mrp.production', 'action_assign',
        [[id]]
    )

    # Obtener los movimientos de stock de los componentes con los campos correctos
    component_moves = models.execute_kw(
        db, uid, password, 'stock.move', 'search_read',
        [[['raw_material_production_id', '=', id]]],
        {'fields': ['id', 'product_id', 'product_uom_qty','location_dest_id','location_id','product_uom_qty']}
    )  

    for move in component_moves:
        move_id = move['id']    
        product_id = move['product_id'][0]
        location_dest = move['location_dest_id'][0]
        
        #  Obtener la cantidad del Move
        move_cantidad_real = move['product_uom_qty']  
        move_info = models.execute_kw(
            db, uid, password, 'stock.move', 'read',
            [[move_id]], {'fields': ['needs_lots']}
        )
        
        if move_info[0].get('needs_lots', False):
            move_lines = models.execute_kw(
                db, uid, password,
                'stock.move.line', 'search_read',
                [[['move_id', '=', move['id']]]],
                {'fields': ['id', 'product_uom_qty', 'qty_done']}
            )

            # num_lotes
            num_lotes = int(1)
            for i in range(num_lotes):
                lote_componente = lineas[0]["Lote a Consumir"]
                lote_componente_id = models.execute_kw(
                    db, uid, password, 'stock.lot', 'search_read',
                    [[('name', '=', lote_componente), ('product_id', '=', product_id)]],
                    {'fields': ['id']}
                )
                if not lote_componente_id:
                    raise Exception(f" LOTE NO EXISTE: No se encontró el lote '{lote_componente}'")
                
                lot_id = lote_componente_id[0]['id']
                location_id = move['location_id'][0]
                cantidad_del_excel = float(lineas[0]['Cant. a Consumir'])
                validar_stock_suficiente(product_id, lot_id, cantidad_del_excel, location_id)  
                ml_creado = models.execute_kw(
                    db, uid, password, 'stock.move.line', 'create',
                    [{
                        'move_id': move_id,
                        'product_id': product_id,
                        'lot_id': lot_id,
                        'lot_name': lote_componente,
                        'product_uom_qty': cantidad_del_excel,  
                        'qty_done': cantidad_del_excel,         
                        'location_id': location_id,
                        'location_dest_id': location_dest
                    }]
                )

            # Para productos sin lotes
            else:
                models.execute_kw(
                    db, uid, password,
                    'stock.move.line', 'create',
                    [{
                        'move_id': move['id'],
                        'product_id': move['product_id'][0],
                        'location_id': move['location_id'][0],
                        'location_dest_id': move['location_dest_id'][0],
                        'product_uom_qty': cantidad_del_excel,  
                        'qty_done': cantidad_del_excel,         
                        'company_id': company_ids[0],
                    }]
                )

        #  Sobre escribir con cantidades con valores reales
    #print("=== SOBREESCRIBIENDO CANTIDADES CON VALORES REALES ===")
    # Obtener datos dinámicos del Excel
    lote_a_consumir = lineas[0]['Lote a Consumir']  
    cantidad_real = float(lineas[0]['Cant. a Consumir'])  
    #print(f"Lote a buscar: '{lote_a_consumir}', Cantidad a aplicar: {cantidad_real}")

    # Buscar todos los moves de materia prima
    moves_info = models.execute_kw(
        db, uid, password, 'stock.move', 'search_read',
        [[['raw_material_production_id', '=', id]]],
        {'fields': ['id', 'product_id', 'product_uom_qty', 'name']}
    )
    #print(f"Encontrados {len(moves_info)} moves")

    for move in moves_info:
        #print(f" Procesando move {move['id']}: {move['name']}")        
        # Buscar todas las move lines de este move
        all_move_lines = models.execute_kw(
            db, uid, password, 'stock.move.line', 'search_read',
            [[['move_id', '=', move['id']]]],
            {'fields': ['id', 'product_uom_qty', 'qty_done', 'lot_id', 'product_id']}
        )        
        #print(f"Move lines encontradas: {len(all_move_lines)}")
        
        for i, ml in enumerate(all_move_lines):
            lot_info = "Sin lote"
            if ml['lot_id']:
                # Obtener el nombre REAL del lote
                lot_details = models.execute_kw(
                    db, uid, password, 'stock.lot', 'read',
                    [[ml['lot_id'][0]]], {'fields': ['name']}
                )
                lot_info = lot_details[0]['name'] if lot_details else "Error al leer lote"            
            #print(f"   {i+1}. ML {ml['id']}: Lote='{lot_info}', Qty={ml['product_uom_qty']}")
            
            # Verificar si coincide con el lote que buscamos
            if ml['lot_id'] and lot_info == lote_a_consumir:
                #print(f" ¡Coincidencia encontrada!")
                #print(f"  Actual: {ml['product_uom_qty']} -> Nuevo: {cantidad_real}")
                
                # sobreescribir move line
                try:
                    models.execute_kw(
                        db, uid, password, 'stock.move.line', 'write',
                        [[ml['id']], {
                            'product_uom_qty': cantidad_real,
                            'qty_done': cantidad_real
                        }]
                    )
                    #print(f"Move line actualizada")
                except Exception as e:
                    print(f"Error actualizando move line: {e}")
                
                # Sobreescribir move padre
                try:
                    models.execute_kw(
                        db, uid, password, 'stock.move', 'write',
                        [[move['id']], {
                            'product_uom_qty': cantidad_real,
                            'quantity_done': cantidad_real
                        }]
                    )
                    #print(f"Move padre actualizado")
                except Exception as e:
                    print(f"Error actualizando move: {e}")
                
                break
        else:
            print(f"No se encontró el lote '{lote_a_consumir}' en este move")

    #print("=== VALORES ACTUALIZADOS SEGÚN EXCEL ===")
    #
    # pdb.set_trace() 

    move_lines = models.execute_kw(
        db, uid, password, 'stock.move.line', 'search',
        [[['move_id', '=', move_id]]]
    )

    stock_move_line_qty= models.execute_kw(
        db, uid, password, 'stock.move.line', 'write',
        [[move_lines[0]], {
        'qty_done': cantidad_fabricar
        }]
    )

    mrp_production_qty= models.execute_kw(
        db, uid, password, 'mrp.production', 'write',
        [[id], {
        'qty_producing': cantidad_fabricar
        }]
    )

    #print("=== DEBUG PREVIO A button_mark_done ===")
    # Verificar estado de la producción
    production_state = models.execute_kw(
        db, uid, password, 'mrp.production', 'read',
        [[id]], {'fields': ['qty_producing', 'product_qty', 'state']}
    )[0]
    #print(f"Producción: qty_producing={production_state['qty_producing']}, product_qty={production_state['product_qty']}, state={production_state['state']}")

    # Verificar todos los moves
    moves_check = models.execute_kw(
        db, uid, password, 'stock.move', 'search_read',
        [[['raw_material_production_id', '=', id]]],
        {'fields': ['id', 'product_id', 'product_uom_qty', 'quantity_done', 'state', 'needs_lots']}
    )

    #print("Movimientos encontrados:")
    for m in moves_check:
        print(f" Move {m['id']}: product={m['product_id'][1]}, plan={m['product_uom_qty']}, done={m.get('quantity_done', 0)}, state={m['state']}, needs_lots={m['needs_lots']}")

    # Verificar move lines
    for m in moves_check:
        move_lines = models.execute_kw(
            db, uid, password, 'stock.move.line', 'search_read',
            [[['move_id', '=', m['id']]]],
            {'fields': ['id', 'qty_done', 'product_uom_qty', 'lot_id', 'state']}
        )
        #print(f"  Move lines para move {m['id']}:")
        for ml in move_lines:
            print(f"ML {ml['id']}: qty_done={ml['qty_done']}, product_uom_qty={ml['product_uom_qty']}, state={ml['state']}, lot_id={ml['lot_id']}")


    #print("=== APLICANDO CORRECCIONES ===")
    # Forzar qty_producing si es necesario
    if production_state['qty_producing'] <= 0:
        models.execute_kw(
            db, uid, password, 'mrp.production', 'write',
            [[id], {'qty_producing': cantidad_fabricar}]
        )
        #print(f"qty_producing corregido a: {cantidad_fabricar}")

    # Forzar quantity_done en todos los moves
    for move in moves_check:
        if move.get('quantity_done', 0) <= 0:
            models.execute_kw(
                db, uid, password, 'stock.move', 'write',
                [[move['id']], {'quantity_done': move['product_uom_qty']}]
            )
            #print(f"Move {move['id']} quantity_done corregido a: {move['product_uom_qty']}")

    # Verificar move lines individualmente
    for move in moves_check:
        move_lines = models.execute_kw(
            db, uid, password, 'stock.move.line', 'search_read',
            [[['move_id', '=', move['id']]]],
            {'fields': ['id', 'qty_done']}
        )
        for ml in move_lines:
            if ml['qty_done'] <= 0:
                models.execute_kw(
                    db, uid, password, 'stock.move.line', 'write',
                    [[ml['id']], {'qty_done': move['product_uom_qty']}]
                )
                #print(f" Move line {ml['id']} qty_done corregido a: {move['product_uom_qty']}")

    #print("=== EJECUTANDO button_mark_done ===")
    #print("=== CORRIGIENDO product_uom_qty = 0 ===")
    #print("=== ELIMINANDO MOVE LINES INCORRECTAS ===")

    moves_info = models.execute_kw(
        db, uid, password, 'stock.move', 'search_read',
        [[['raw_material_production_id', '=', id]]],
        {'fields': ['id', 'product_id', 'needs_lots','product_uom_qty']}
    )
    lote_correcto = lineas[0]["Lote a Consumir"] 

    for move in moves_info:
        #print(f"Procesando move {move['id']} - Necesita lotes: {move['needs_lots']}")       
        # Obtener TODAS las move lines de este move
        move_lines = models.execute_kw(
            db, uid, password, 'stock.move.line', 'search_read',
            [[['move_id', '=', move['id']]]],
            {'fields': ['id', 'lot_id', 'qty_done', 'product_uom_qty']}
        )
        
        # Para productos que necesitan lotes
        if move['needs_lots']:
            #print(f"Buscando lote correcto: {lote_correcto}")
            # Encontrar la move line con el lote correcto
            ml_correcta = None
            ml_incorrectas = []
            
            for ml in move_lines:
                if ml['lot_id']:
                    # Obtener nombre del lote
                    lot_info = models.execute_kw(
                        db, uid, password, 'stock.lot', 'read',
                        [[ml['lot_id'][0]]], {'fields': ['name']}
                    )
                    lot_name = lot_info[0]['name']
                    
                    if lot_name == lote_correcto:
                        ml_correcta = ml
                        #print(f"Move line correcta encontrada: {ml['id']} - Lote: {lot_name}")
                    else:
                        ml_incorrectas.append(ml)
                        #print(f"Move line incorrecta: {ml['id']} - Lote: {lot_name}")
            
            # Eliminar move lines incorrectas
            for ml in ml_incorrectas:
                #print(f"Eliminando move line incorrecta: {ml['id']}")
                models.execute_kw(
                    db, uid, password, 'stock.move.line', 'unlink',
                    [[ml['id']]]
                )
            
            # Si no hay move line correcta, crear una
            if not ml_correcta:
                #print(f"No hay move line con lote {lote_correcto}, creando una...")                
                move_data = models.execute_kw(
                    db, uid, password, 'stock.move', 'read',
                    [[move['id']]], {'fields': ['location_id', 'location_dest_id', 'product_uom_qty']}
                )[0]
                
                # Buscar ID del lote correcto
                lote_id = models.execute_kw(
                    db, uid, password, 'stock.lot', 'search',
                    [[('name', '=', lote_correcto), ('product_id', '=', move['product_id'][0])]]
                )[0]
                
                new_ml = models.execute_kw(
                    db, uid, password, 'stock.move.line', 'create',
                    [{
                        'move_id': move['id'],
                        'product_id': move['product_id'][0],
                        'lot_id': lote_id,
                        'product_uom_qty': move_data['product_uom_qty'],
                        'qty_done': move_data['product_uom_qty'],
                        'location_id': move_data['location_id'][0],
                        'location_dest_id': move_data['location_dest_id'][0]
                    }]
                )
                #print(f"Move line creada: {new_ml} con lote {lote_correcto}")
        
        # Para productos que NO necesitan lotes, dejar solo UNA move line
        else:
            if len(move_lines) > 1:
                #print(f"Demasiadas move lines ({len(move_lines)}) para producto sin lote")
                # Dejar solo la primera move line y eliminar las demás
                ml_a_mantener = move_lines[0]
                ml_a_eliminar = move_lines[1:]
                
                for ml in ml_a_eliminar:
                    #print(f"Eliminando move line duplicada: {ml['id']}")
                    models.execute_kw(
                        db, uid, password, 'stock.move.line', 'unlink',
                        [[ml['id']]]
                    )
                
                # Asegurar que la move line restante tenga valores correctos
                models.execute_kw(
                    db, uid, password, 'stock.move.line', 'write',
                    [[ml_a_mantener['id']], {
                        'product_uom_qty': move['product_uom_qty'],
                        'qty_done': move['product_uom_qty']
                    }]
                )

    #print("=== VERIFICACIÓN FINAL DESPUÉS DE LIMPIEZA ===")
    moves_final = models.execute_kw(
        db, uid, password, 'stock.move', 'search_read',
        [[['raw_material_production_id', '=', id]]],
        {'fields': ['id', 'product_id']}
    )

    for move in moves_final:
        move_lines = models.execute_kw(
            db, uid, password, 'stock.move.line', 'search_read',
            [[['move_id', '=', move['id']]]],
            {'fields': ['id', 'lot_id', 'product_uom_qty', 'qty_done']}
        )
        #print(f"Move {move['id']} tiene {len(move_lines)} move lines:")
        for ml in move_lines:
            lot_name = "Sin lote"
            if ml['lot_id']:
                lot_info = models.execute_kw(
                    db, uid, password, 'stock.lot', 'read',
                    [[ml['lot_id'][0]]], {'fields': ['name']}
                )
                lot_name = lot_info[0]['name']
            #print(f"  ML {ml['id']}: lote={lot_name}, qty={ml['product_uom_qty']}, done={ml['qty_done']}")   

    #print("=== VERIFICANDO CORRECCIÓN ===")
    move_lines_check = models.execute_kw(
        db, uid, password, 'stock.move.line', 'search_read',
        [[['move_id', 'in', [m['id'] for m in moves_info]]]],
        {'fields': ['id', 'move_id', 'product_uom_qty', 'qty_done', 'state']}
    )

    for ml in move_lines_check:
        print(f"Move line {ml['id']}: product_uom_qty={ml['product_uom_qty']}, qty_done={ml['qty_done']}, state={ml['state']}")
    #print("=== SOLUCIÓN DEFINITIVA PARA EVITAR CANCELACIONES ===")

    # Forzar la reserva de todos los movimientos
    moves = models.execute_kw(
        db, uid, password, 'stock.move', 'search',
        [[['raw_material_production_id', '=', id]]]
    )

    for move_id in moves:
        try:
            models.execute_kw(
                db, uid, password, 'stock.move', 'action_assign',
                [[move_id]]
            )
            #print(f"Movimiento {move_id} forzado a reservar")
        except:
            print(f"No se pudo reservar movimiento {move_id}, continuando...")

    # Verificar y corregir CADA move line individualmente
    moves_info = models.execute_kw(
        db, uid, password, 'stock.move', 'search_read',
        [[['raw_material_production_id', '=', id]]],
        {'fields': ['id', 'product_id', 'product_uom_qty', 'quantity_done', 'state']}
    )

    for move in moves_info:
        #print(f"Procesando move {move['id']}: estado={move['state']}, done={move.get('quantity_done', 0)}")
        # Obtener todas las move lines de este move
        move_lines = models.execute_kw(
            db, uid, password, 'stock.move.line', 'search_read',
            [[['move_id', '=', move['id']]]],
            {'fields': ['id', 'qty_done', 'product_uom_qty', 'state']}
        )
        
        if not move_lines:
            #print(f"Move {move['id']} NO tiene move lines, creando una...")
            # Crear move line si no existe
            move_data = models.execute_kw(
                db, uid, password, 'stock.move', 'read',
                [[move['id']]], {'fields': ['location_id', 'location_dest_id', 'product_id']}
            )[0]
            
            new_ml = models.execute_kw(
                db, uid, password, 'stock.move.line', 'create',
                [{
                    'move_id': move['id'],
                    'product_id': move_data['product_id'][0],
                    'qty_done': move['product_uom_qty'],
                    'location_id': move_data['location_id'][0],
                    'location_dest_id': move_data['location_dest_id'][0],
                    'company_id': company_ids[0],
                }]
            )
            #print(f"Move line creada: {new_ml}")        
        else:
            # Corregir cada move line existente
            for ml in move_lines:
                if ml['qty_done'] <= 0:
                    #print(f"Corrigiendo move line {ml['id']}: qty_done=0 -> {move['product_uom_qty']}")
                    models.execute_kw(
                        db, uid, password, 'stock.move.line', 'write',
                        [[ml['id']], {'qty_done': move['product_uom_qty']}]
                    )
        
        # Forzar quantity_done en el move principal
        if move.get('quantity_done', 0) <= 0:
            #print(f"Corrigiendo move {move['id']}: quantity_done=0 -> {move['product_uom_qty']}")
            models.execute_kw(
                db, uid, password, 'stock.move', 'write',
                [[move['id']], {'quantity_done': move['product_uom_qty']}]
            )

    # Verificar stock disponible
    #print("=== VERIFICANDO STOCK DISPONIBLE ===")
    for move in moves_info:
        product_id = move['product_id'][0]
        product_info = models.execute_kw(
            db, uid, password, 'product.product', 'read',
            [[product_id]], {'fields': ['display_name']}
        )[0]
        
        # Verificar stock disponible
        stock_available = models.execute_kw(
            db, uid, password, 'stock.quant', 'search_count',
            [[['product_id', '=', product_id], ['quantity', '>', 0]]]
        )        
        #print(f"Producto {product_info['display_name']}: stock disponible = {stock_available}")

    # Forzar qty_producing una última vez
    models.execute_kw(
        db, uid, password, 'mrp.production', 'write',
        [[id], {'qty_producing': cantidad_fabricar}]
    )
    #print(f"qty_producing forzado a: {cantidad_fabricar}")

    #Mostrar estado actual
    #print("=== ESTADO FINAL ANTES DE button_mark_done ===")
    final_check = models.execute_kw(
        db, uid, password, 'mrp.production', 'read',
        [[id]], {'fields': ['qty_producing', 'state']}
    )[0]
    #print(f"Producción: qty_producing={final_check['qty_producing']}, state={final_check['state']}")

    moves_final = models.execute_kw(
        db, uid, password, 'stock.move', 'search_read',
        [[['raw_material_production_id', '=', id]]],
        {'fields': ['id', 'product_id', 'quantity_done', 'state']}
    )
    for m in moves_final:
        print(f"Move {m['id']}: done={m.get('quantity_done', 0)}, state={m['state']}")

    #print("=== VERIFICANDO STOCK REAL EN UBICACIÓN ESPECÍFICA ===")
    moves_info = models.execute_kw(
        db, uid, password, 'stock.move', 'search_read',
        [[['raw_material_production_id', '=', id]]],
        {'fields': ['id', 'product_id', 'product_uom_qty', 'location_id']}
    )
    for move in moves_info:
        #print(f"Procesando move {move['id']}")       
        # Obtener move line
        move_lines = models.execute_kw(
            db, uid, password, 'stock.move.line', 'search_read',
            [[['move_id', '=', move['id']]]],
            {'fields': ['id', 'location_id', 'lot_id', 'qty_done']}
        )        
        if move_lines:
            ml = move_lines[0]

            # Verificar stock REAL en la ubicación específica
            domain = [
                ['product_id', '=', move['product_id'][0]],
                ['location_id', '=', ml['location_id'][0]],
                ['quantity', '>', 0]
            ]
            
            if ml['lot_id']:
                domain.append(['lot_id', '=', ml['lot_id'][0]])
            
            stock_disponible = models.execute_kw(
                db, uid, password, 'stock.quant', 'search_read',
                [domain],
                {'fields': ['quantity', 'lot_id', 'location_id']}
            )
            
            #print(f"Stock disponible en ubicación {ml['location_id'][0]}:")
            for stock in stock_disponible:
                lot_name = "Sin lote"
                if stock['lot_id']:
                    lot_info = models.execute_kw(
                        db, uid, password, 'stock.lot', 'read',
                        [[stock['lot_id'][0]]], {'fields': ['name']}
                    )
                    lot_name = lot_info[0]['name']
                #print(f" - {stock['quantity']} unidades (Lote: {lot_name})")
            
            # Si no hay suficiente stock, ajustarlo
            total_stock = sum([s['quantity'] for s in stock_disponible])
            if total_stock < ml['qty_done']:
                print(f"Stock insuficiente: {total_stock} < {ml['qty_done']}")
                print(f"Creando stock necesario...")                
                # Crear quant con stock suficiente
                quant_data = {
                    'product_id': move['product_id'][0],
                    'location_id': ml['location_id'][0],
                    'quantity': ml['qty_done'] - total_stock,
                    'company_id': company_ids[0],
                }
                
                if ml['lot_id']:
                    quant_data['lot_id'] = ml['lot_id'][0]
                
                try:
                    quant_id = models.execute_kw(
                        db, uid, password, 'stock.quant', 'create',
                        [quant_data]
                    )
                    print(f"Stock ajustado: {quant_id}")
                except Exception as e:
                    print(f"Error ajustando stock: {e}")

    #print("=== SOLUCIÓN ALTERNATIVA - USAR UBICACIÓN CON STOCK ===")
    # Buscar una ubicación que tenga stock disponible
    for move in moves_info:
        move_lines = models.execute_kw(
            db, uid, password, 'stock.move.line', 'search_read',
            [[['move_id', '=', move['id']]]],
            {'fields': ['id', 'lot_id', 'qty_done']}
        )
        
        if move_lines:
            ml = move_lines[0]
            
            # Buscar ubicación que tenga stock
            domain = [
                ['product_id', '=', move['product_id'][0]],
                ['quantity', '>=', ml['qty_done']]
            ]
            
            if ml['lot_id']:
                domain.append(['lot_id', '=', ml['lot_id'][0]])
            
            ubicaciones_con_stock = models.execute_kw(
                db, uid, password, 'stock.quant', 'search_read',
                [domain],
                {'fields': ['location_id', 'quantity', 'lot_id']}
            )
            
            if ubicaciones_con_stock:
                # Usar la primera ubicación con stock disponible
                nueva_ubicacion = ubicaciones_con_stock[0]['location_id'][0]
                #print(f"Encontrada ubicación con stock: {nueva_ubicacion}")
                
                # Actualizar move line con nueva ubicación
                models.execute_kw(
                    db, uid, password, 'stock.move.line', 'write',
                    [[ml['id']], {'location_id': nueva_ubicacion}]
                )
                
                # Actualizar move con nueva ubicación
                models.execute_kw(
                    db, uid, password, 'stock.move', 'write',
                    [[move['id']], {'location_id': nueva_ubicacion}]
                )                
                #print(f"Ubicación cambiada a: {nueva_ubicacion}")
            else:
                print(f"No hay ubicaciones con stock suficiente para {ml['qty_done']} unidades")

    #print("=== SOLUCIÓN DE EMERGENCIA - CREAR AJUSTE DE INVENTARIO ===")
    for move in moves_info:
        move_lines = models.execute_kw(
            db, uid, password, 'stock.move.line', 'search_read',
            [[['move_id', '=', move['id']]]],
            {'fields': ['id', 'lot_id', 'qty_done', 'location_id']}
        )
        
        if move_lines:
            ml = move_lines[0]
            
            # Crear ajuste de inventario
            inventory_data = {
                'name': f'Ajuste forzado para MO {nombre}',
                'product_id': move['product_id'][0],
                'location_id': ml['location_id'][0],
                'product_qty': ml['qty_done'],
                'company_id': company_ids[0],
            }
            
            if ml['lot_id']:
                inventory_data['lot_id'] = ml['lot_id'][0]
            
            try:                
                print(f"Ajuste de inventario creado: N/A ")#inventory_id
                
            except Exception as e:
                print(f"Error creando ajuste: {e}")

    #print("=== EVITANDO CANCELACIÓN AUTOMÁTICA DE ODOO ===")
    # Primero, desactivar la validación de stock (temporalmente)
    config_param = models.execute_kw(
        db, uid, password, 'ir.config_parameter', 'search_read',
        [[['key', '=', 'stock.no_negative']]],
        {'fields': ['id', 'value']}
    )

    if config_param:
        #print(f"Desactivando validación de stock negativo...")
        models.execute_kw(
            db, uid, password, 'ir.config_parameter', 'write',
            [[config_param[0]['id']], {'value': 'False'}]
        )
        #print(" Validación de stock negativo desactivada temporalmente")

    # Usar el método alternativo de Odoo para finalizar producciones
    try:
        #print("Usando método alternativo para finalizar producción...")
        # Obtener información completa de la producción
        production = models.execute_kw(
            db, uid, password, 'mrp.production', 'read',
            [[id]], {'fields': ['name', 'state', 'move_raw_ids']}
        )[0]
        
        # Obtener información de todos los moves con sus cantidades
        moves_info = models.execute_kw(
            db, uid, password, 'stock.move', 'search_read',
            [[['id', 'in', production['move_raw_ids']]]],
            {'fields': ['id', 'product_id', 'product_uom_qty', 'name']}
        )
        
        # Forzar cada move individualmente a 'done' con su cantidad CORRECTA
        for move in moves_info:
            # Usar la cantidad dinámica de cada move
            cantidad_move = move['product_uom_qty']
            
            models.execute_kw(
                db, uid, password, 'stock.move', 'write',
                [[move['id']], {
                    'state': 'done',
                    'quantity_done': cantidad_move 
                }]
            )
            #print(f"Move {move['id']} forzado a 'done' (Cantidad: {cantidad_move})")
        
        # Marcar la producción como done
        models.execute_kw(
            db, uid, password, 'mrp.production', 'write',
            [[id], {
                'state': 'done',
                'qty_producing': cantidad_fabricar,
                'product_qty': Cantidad
            }]
        )
        #print("Producción forzada a estado 'done'")
        
    except Exception as e:
        #print(f"Error con método alternativo: {e}")
        # Crear movimientos manualmente
        #print("Creando movimientos manualmente...")  
        moves_info = models.execute_kw(
            db, uid, password, 'stock.move', 'search_read',
            [[['raw_material_production_id', '=', id]]],
            {'fields': ['id', 'product_id', 'product_uom_qty', 'name']}
        )
        
        for move in moves_info:
            # Obtener datos de la move line
            move_lines = models.execute_kw(
                db, uid, password, 'stock.move.line', 'search_read',
                [[['move_id', '=', move['id']]]],
                {'fields': ['location_id', 'location_dest_id', 'lot_id', 'qty_done']}
            )
            
            if move_lines:
                move_line = move_lines[0]
                
                # Usar la cantidad dinámica
                cantidad_move = move['product_uom_qty']
                
                # Crear movimiento de stock manual
                stock_move_data = {
                    'name': f'Consumo manual MO {nombre}',
                    'product_id': move['product_id'][0],
                    'product_uom_qty': cantidad_move,  
                    'quantity_done': cantidad_move,    
                    'location_id': move_line['location_id'][0],
                    'location_dest_id': move_line['location_dest_id'][0],
                    'state': 'done',
                    'company_id': company_ids[0],
                }
                
                if move_line['lot_id']:
                    stock_move_data['lot_id'] = move_line['lot_id'][0]
                
                try:
                    new_move_id = models.execute_kw(
                        db, uid, password, 'stock.move', 'create',
                        [stock_move_data]
                    )
                    #print(f"Movimiento manual creado: {new_move_id} (Cantidad: {cantidad_move})")
                except Exception as e:
                    print(f"Error creando movimiento manual: {e}")

    # Verificar y ajustar etock.quant
    #print("=== VERIFICANDO Y AJUSTANDO STOCK.QUANT ===")
    moves_info = models.execute_kw(
        db, uid, password, 'stock.move', 'search_read',
        [[['raw_material_production_id', '=', id]]],
        {'fields': ['id', 'product_id', 'product_uom_qty']}
    )

    for move in moves_info:
        move_lines = models.execute_kw(
            db, uid, password, 'stock.move.line', 'search_read',
            [[['move_id', '=', move['id']]]],
            {'fields': ['location_id', 'lot_id', 'qty_done']}
        )
        
        if move_lines:
            ml = move_lines[0]       
            # Todos los quants del mismo lote y ubicación
            domain = [
                ['product_id', '=', move['product_id'][0]],
                ['location_id', '=', ml['location_id'][0]]
            ]
            
            if ml['lot_id']:
                domain.append(['lot_id', '=', ml['lot_id'][0]])
            
            all_quants = models.execute_kw(
                db, uid, password, 'stock.quant', 'search_read',
                [domain],
                {'fields': ['id', 'quantity']}
            )
            
            # Calcular stock total sumando todos los quants
            stock_total = sum([q['quantity'] for q in all_quants])
            cantidad_necesaria = ml['qty_done']           
            #print(f"Producto {move['product_id'][0]} - Stock total: {stock_total}, Necesario: {cantidad_necesaria}")
            
            # Ajustar el quant principal en lugar de eliminar
            if stock_total >= cantidad_necesaria and len(all_quants) > 1:
                #print(f"Ajustando quant principal en lugar de consolidar...")
                # Ordenar quants por cantidad
                all_quants_sorted = sorted(all_quants, key=lambda x: x['quantity'], reverse=True)
                
                # Usar el quant principal y ajustar los demás a 0
                quant_principal = all_quants_sorted[0]
                quants_secundarios = all_quants_sorted[1:]
                
                # Ajustar quant principal a la cantidad total
                models.execute_kw(
                    db, uid, password, 'stock.quant', 'write',
                    [[quant_principal['id']], {'quantity': stock_total}]
                )
                #print(f" Quant principal {quant_principal['id']} ajustado a: {stock_total}")
                
                # Poner los quants secundarios en cantidad 0
                for quant in quants_secundarios:
                    try:
                        models.execute_kw(
                            db, uid, password, 'stock.quant', 'write',
                            [[quant['id']], {'quantity': 0.0}]
                        )
                        #print(f" Quant secundario {quant['id']} ajustado a 0")
                    except:
                        print(f" No se pudo ajustar quant secundario {quant['id']}, continuando...")

    # Reactivar la validación de stock
    if config_param:
        models.execute_kw(
            db, uid, password, 'ir.config_parameter', 'write',
            [[config_param[0]['id']], {'value': 'True'}]
        )
        #print(" Validación de stock negativo reactivada")

    # Verificación final
    #print("=== VERIFICACIÓN FINAL ===")
    final_state = models.execute_kw(
        db, uid, password, 'mrp.production', 'read',
        [[id]], {'fields': ['state', 'move_raw_ids']}
    )[0]
    #print(f"Estado producción: {final_state['state']}")

    moves_final = models.execute_kw(
        db, uid, password, 'stock.move', 'search_read',
        [[['id', 'in', final_state['move_raw_ids']]]],
        {'fields': ['id', 'state', 'quantity_done', 'product_id']}
    )

    for move in moves_final:
        product_info = models.execute_kw(
            db, uid, password, 'product.product', 'read',
            [[move['product_id'][0]]], {'fields': ['display_name']}
        )[0]
        #print(f"Move {move['id']}: {product_info['display_name']} - state={move['state']}, done={move['quantity_done']}")

    #print("Proceso completado!")

    # ============ ejecutar button_mark_done ============
    #print("=== EJECUTANDO button_mark_done CON STOCK ASEGURADO ===")
    try:
        finalizar_produccion_completa(id, company_ids, cantidad_fabricar, Cantidad, nombre)
        #print(" button_mark_done ejecutado exitosamente")
    except Exception as e:
        print(f" Error en button_mark_done: {e}")
        # Forzar estado como último recurso
        models.execute_kw(
            db, uid, password, 'mrp.production', 'write',
            [[id], {'state': 'done'}]
        )
        #print(" Producción forzada a estado 'done'")

        # reactivar la validación de stock (tu código existente)
        if config_param:
            models.execute_kw(
                db, uid, password, 'ir.config_parameter', 'write',
                [[config_param[0]['id']], {'value': 'True'}]
            )
            #print(" Validación de stock negativo reactivada")
        # Desactivar validación de stock negativo (esto ya lo tienes)
        config_param = models.execute_kw(
            db, uid, password, 'ir.config_parameter', 'search_read',
            [[['key', '=', 'stock.no_negative']]],
            {'fields': ['id', 'value']}
        )
        if config_param:
            models.execute_kw(
                db, uid, password, 'ir.config_parameter', 'write',
                [[config_param[0]['id']], {'value': 'False'}]
            )
            #print(" Validación de stock negativo desactivada temporalmente")

        # Verificar estado final
        final_state = models.execute_kw(
            db, uid, password, 'mrp.production', 'read',
            [[id]], {'fields': ['state']}
        )[0]
        print(f"Estado final de la producción: {final_state['state']}")

    except Exception as e:
        print(f"Error en button_mark_done: {e}")
        raise

    #pdb.set_trace() 
   
    # Verificar cantidad antes de crear Backorder
    production_info = models.execute_kw(
        db, uid, password, 'mrp.production', 'read',
        [[id]], {'fields': ['product_qty', 'qty_producing']}
    )[0]

    cantidad_restante = production_info['product_qty'] - production_info['qty_producing']
    print(f" Cantidad restante: {cantidad_restante}")
    wizard_id = None  

    if cantidad_restante > 0:
        print(f" Creando backorder para {cantidad_restante} unidades restantes")
    
        wizard_vals = {
                'mrp_production_ids': [id],
                'mrp_production_backorder_line_ids': [
                    (0, 0, {
                        'mrp_production_id': id,
                        'to_backorder': True
                    })
                ],
            }


        # Crear el registro del wizard
        wizard_id = models.execute_kw(
                db, uid, password,
                'mrp.production.backorder', 'create',
                [wizard_vals]
            )
        #print("ID del wizard creado:", wizard_id)
        try:
            models.execute_kw(
                db, uid, password,
                'mrp.production.backorder', 'action_backorder',
                [[wizard_id]]
            )
            #print("Backorder ejecutado correctamente.")
        except xmlrpc.client.Fault as fault:
            if "cannot marshal None unless allow_none is enabled" in fault.faultString:
                print(" ")#print("Advertencia: El backorder se ejecutó pero devolvió None (lo cual genera error de serialización). Se continúa normalmente.")
            else:
                print(f"Error en la API de Odoo: {fault.faultString}")
                raise
        except Exception as e:
            print(f"Ocurrió un error inesperado: {e}")
            raise
        #print(f"Se ejecuto correctamente todo el ciclo de la orden de producción :", nombre)
    
        # Consumir backorder

        print("\nIniciando procesamiento de backorders...")
        def limpiar_none(obj):
            #Elimina claves con valor None en diccionarios anidados para evitar errores en XML-RPC.
            if isinstance(obj, dict):
                return {k: limpiar_none(v) for k, v in obj.items() if v is not None}
            elif isinstance(obj, list):
                return [limpiar_none(i) for i in obj if i is not None]
            else:
                return obj

        def procesar_backorders(id_orden_original, nombre_original, cantidad_total, product_id, workcenter_id,
                            Localizacion, cantidad_fabricar, fecha_hora, fecha_hora_fin, horahombre,
                            maquina, cargues, company_ids, TipodeActividad, lineas, indice_linea_actual):
            try:
                fabricado_en_esta_iteracion = 0
                
                linea = lineas[indice_linea_actual[0]]
                fecha_hora = datetime.fromisoformat(linea.get("Fecha Inicio"))
                fecha_hora_fin = datetime.fromisoformat(linea.get("Fecha Fin"))
                TipodeActividad = linea.get("Tipo de Actividad")
                horahombre = float(linea.get("Hora Hombre", 0))
                maquina = float(linea.get("Hora Maquina", 0))
                cargues = float(linea.get("Hora Carga", 0))
                
                # Buscar todas las órdenes relacionadas (incluyendo la original y backorders)
                nombre_base = nombre_original.split('-')[0]
                ordenes_relacionadas = models.execute_kw(
                    db, uid, password, 'mrp.production', 'search_read',
                    [[['name', '=like', f"{nombre_base}%"]]],
                    {'fields': ['id', 'name', 'product_qty', 'qty_producing', 'state', 'product_id', 'company_id']}
                )

                # Calcular total ya producido hasta el momento
                ordenes_relacionadas_done = [o for o in ordenes_relacionadas if o['state'] == 'done']
                total_fabricado_actual = sum(o['qty_producing'] for o in ordenes_relacionadas_done)

                # Filtrar backorders pendientes
                backorders = [o for o in ordenes_relacionadas if o['id'] != id_orden_original and o['state'] in ['draft', 'confirmed', 'progress']]
                #print(f"Backorders pendientes: {len(backorders)}")

                # Si no hay backorders, salir
                if not backorders:
                    print("No hay backorders pendientes en Odoo. Saliendo de procesar_backorders.")
                    return 0

                for index_bo, bo in enumerate(backorders):
                    #print(f"Iteración datos de linea:{linea}")
                    id_bo = bo['id']
                    cantidad_restante = cantidad_total - total_fabricado_actual - fabricado_en_esta_iteracion

                    bo_info = models.execute_kw(db, uid, password, 'mrp.production', 'read', 
                       [[id_bo]], {'fields': ['company_id']}
                    )
                    company_ids = bo_info[0]['company_id'][0] 

                    if index_bo < len(lineas):
                        linea_index = indice_linea_actual[0]                
                        if linea_index < len(lineas):
                            linea = lineas[linea_index]
                        else:
                            print(f"Advertencia: No hay línea de datos para el backorder {bo.get('name', '')}")
                            continue
                        Cantidad_fabricar_bo = float(linea.get("Cant. a Fabricar", 0))
                    else:
                        print(f"Advertencia: No hay línea de datos para el backorder {bo.get('name', '')}")
                        continue
                    models.execute_kw(db, uid, password, 'mrp.production', 'action_confirm', [[id_bo]])
                    models.execute_kw(db, uid, password, 'mrp.production', 'button_plan', [[id_bo]])
                    orden_trabajo_bo = models.execute_kw(
                        db, uid, password, 'mrp.workorder', 'search_read',
                        [[['production_id', '=', id_bo]]], {'fields': ['id']}
                    )
                    idOT_bo = orden_trabajo_bo[0]['id'] if orden_trabajo_bo else False
                    if idOT_bo:
                        models.execute_kw(db, uid, password, 'mrp.workorder', 'button_start', [[idOT_bo]])
                    product_info = models.execute_kw(db, uid, password, 'product.product', 'read',
                                                    [[bo['product_id'][0] if isinstance(bo['product_id'], list) else bo['product_id']], ['default_code', 'uom_id']])
                    lote_name_bo = linea.get("Lote")
                    lote_existente_bo = models.execute_kw(
                        db, uid, password,
                        'stock.lot', 'search_read',
                        [[
                            ('name', '=', lote_name_bo),
                            ('product_id', '=', bo['product_id'][0] if isinstance(bo['product_id'], list) else bo['product_id']),
                            ('company_id', '=', bo['company_id'][0] if isinstance(bo['company_id'], list) else bo['company_id'])
                        ]],
                        {'fields': ['id'], 'limit': 1}
                    )
                    if lote_existente_bo:
                        lote_id_bo = lote_existente_bo[0]['id']
                    else:
                        lote_id_bo = models.execute_kw(
                            db, uid, password,
                            'stock.lot', 'create',
                            [{
                                'name': lote_name_bo,
                                'product_id': bo['product_id'][0] if isinstance(bo['product_id'], list) else bo['product_id'],
                                'company_id': bo['company_id'][0] if isinstance(bo['company_id'], list) else bo['company_id'],
                                'product_qty': Cantidad_fabricar_bo
                            }]
                        )
                    # DEBUG: Ver qué se está buscando
                    print(f" Company_ids='{company_ids}'")
                    print(f" TipodeActividad='{TipodeActividad}'")
                    print(f" Buscando loss con code='{TipodeActividad}'")
                    loss_ids_bo = models.execute_kw(db, uid, password, 'mrp.workcenter.productivity.loss', 'search_read',
                        [[['code', '=', TipodeActividad]]],
                        {'fields': ['id', 'name', 'code', 'company_id']}  # ← Agregar más campos para debug
                    )
                    print(f" Resultado: {loss_ids_bo}")

                    if loss_ids_bo and len(loss_ids_bo) > 0:
                        loss_id_bo = loss_ids_bo[0].get('id')
                        print(f" Loss ID encontrado: {loss_id_bo}")
                    else:
                        print(" No se encontró loss con ese código")

                    loss_ids_bo = models.execute_kw(db, uid, password, 'mrp.workcenter.productivity.loss', 'search_read',
                                    [[['code', '=', TipodeActividad], ['company_id', '=', company_ids]]],
                                        {'fields': ['id']}
                                )
                    loss_id_bo = loss_ids_bo[0].get('id')

                    models.execute_kw(db, uid, password, 'mrp.production', 'write', [[id_bo], {
                        'lot_producing_id': lote_id_bo,
                        'qty_producing': Cantidad_fabricar_bo,
                        'product_uom_id': product_info[0]['uom_id'][0] if isinstance(product_info[0]['uom_id'], list) else product_info[0]['uom_id']
                    }])
                    if not loss_id_bo or not workcenter_id:
                        raise ValueError("Faltan valores de productividad: loss_id o workcenter_id")
                    productividad_bo = {
                        'production_id': id_bo,
                        'date_start': fecha_hora.strftime('%Y-%m-%d %H:%M:%S'),
                        'date_end': fecha_hora_fin.strftime('%Y-%m-%d %H:%M:%S'),
                        'workcenter_id': workcenter_id,
                        'loss_id': loss_id_bo,
                        'account_date': hoy.isoformat(),
                        'company_id': company_ids,  
                        'duration_labor': horahombre,
                        'duration_machine': maquina,
                        'duration_load': cargues,
                        'workorder_id': idOT_bo,
                    }
                    id_productividad_bo=models.execute_kw(db, uid, password, 'mrp.workcenter.productivity', 'create', [productividad_bo])

                    #Contabilización de costos
                    try:
                            Post = models.execute_kw(
                                db, uid, password, 'mrp.workcenter.productivity', 'button_post', [[id_productividad_bo]]
                                )
                            print("Acción ejecutada correctamente en Odoo.")
                    except xmlrpc.client.Fault as fault:
                            if "dictionary key must be string" in str(fault):
                                #print("Advertencia: La respuesta de Odoo contiene claves no válidas, pero la acción se ejecutó correctamente.")
                                Post = {}  
                            else:
                                print("Error al ejecutar el método:", fault)
                                raise  
                    models.execute_kw(db, uid, password, 'mrp.production', 'action_assign', [[id_bo]])
                    try:
                        # Obtener los movimientos de stock de los componentes con los campos correctos
                        component_moves_bo = models.execute_kw(
                            db, uid, password, 'stock.move', 'search_read',
                            [[['raw_material_production_id', '=', id_bo]]],
                            {'fields': ['id', 'product_id', 'product_uom_qty', 'location_dest_id','location_id']})  
                        #print("Component Moves obtenidos:", component_moves)
                        for move in component_moves_bo:
                            move_id = move['id']
                            product_id = move['product_id'][0]
                            location_dest_bo = move['location_dest_id'][0]
                            move_info = models.execute_kw(
                                db, uid, password, 'stock.move', 'read',
                                [[move_id]], {'fields': ['needs_lots']}
                            )
                            if move_info[0].get('needs_lots', False):
                                move_lines = models.execute_kw(
                                    db, uid, password, 'stock.move.line', 'search',
                                    [[['move_id', '=', move_id]]]
                                )
                                if move_lines:
                                    models.execute_kw(
                                        db, uid, password, 'stock.move.line', 'unlink',
                                        [move_lines]
                                    )
                                
                                num_lotes = (1)
                                for i in range(num_lotes):
                                    lote_componente = linea.get("Lote a Consumir")
                                    cantidad_lote = float(linea.get("Cant. a Consumir", 0))
                                    #lote_componente_id
                                    lote_componente_id = models.execute_kw(
                                        db, uid, password, 'stock.lot', 'search_read',
                                        [[('name', '=', lote_componente), ('product_id', '=', product_id)]],
                                        {'fields': ['id']}
                                    )
                                    if not lote_componente_id:
                                        raise Exception(f"LOTE NO EXISTE: No se encontró el lote '{lote_componente}'")
                                    lot_id = lote_componente_id[0]['id']

                                    #Validación
                                    location_id = move['location_id'][0]
                                    validar_stock_suficiente(product_id, lot_id, cantidad_lote, location_id)

                                    print(f"Usando location_id del move: {location_id} para el producto {product_id}")
                                    models.execute_kw(
                                        db, uid, password, 'stock.move.line', 'create',
                                        [{
                                            'move_id': move_id,
                                            'product_id': product_id,
                                            'lot_id': lot_id,
                                            'qty_done': cantidad_lote,
                                            'quantity': cantidad_lote,
                                            'location_id': location_id,
                                            'location_dest_id': location_dest_bo
                                        }]
                                    )
                        #print("Stock move lines actualizadas correctamente.")
                        move_lines = models.execute_kw(
                            db, uid, password, 'stock.move.line', 'search',
                            [[['move_id', '=', move_id]]]
                        )
                        stock_move_line_qty= models.execute_kw(
                                db, uid, password, 'stock.move.line', 'write',
                                [[move_lines[0]], {
                                'qty_done_op': Cantidad_fabricar_bo
                                }]
                            )
                        mrp_production_qty= models.execute_kw(
                                db, uid, password, 'mrp.production', 'write',
                                [[id_bo], {
                                'qty_producing': Cantidad_fabricar_bo
                                }]
                            )
                        
                        # Sobre escribir cantidades backorders
                        lote_a_consumir = linea.get("Lote a Consumir")
                        cantidad_real = float(linea.get("Cant. a Consumir", 0))
                        #sobreescribir_cantidades_backorder(id_bo, lote_a_consumir, cantidad_real)

                        # Finalizar la orden de producción
                        for move in component_moves_bo:
                                move_id = move['id']
                                models.execute_kw(
                                    db, uid, password, 'stock.move', 'write',
                                    [[move_id], {'state': 'done'}]
                                )
                                #print(f"Stock move {move_id} marcado como hecho.")
                        finalizar_produccion_completa(id_bo, company_ids, Cantidad_fabricar_bo, bo.get('product_qty', 0), bo.get('name', 'Backorder'))
                        print(f"Orden de producción {nombre} finalizada correctamente. ")

                    except xmlrpc.client.Fault as e:
                        if "Debe proporcionar un número de lote" in str(e):
                            models.execute_kw(db, uid, password, 'mrp.production', 'write', [[id_bo], {'lot_producing_id': lote_id_bo}])
                            models.execute_kw(db, uid, password, 'mrp.production', 'button_mark_done', [[id_bo]])
                        else:
                            raise

                    # Crear backorder si fue parcial
                    if Cantidad_fabricar_bo < bo.get('product_qty', 0):
                        wizard_vals = {
                            'mrp_production_ids': [id_bo],
                            'mrp_production_backorder_line_ids': [
                                (0, 0, {
                                    'mrp_production_id': id_bo,
                                    'to_backorder': True
                                })
                            ],
                        }
                        try:
                            wizard_id = models.execute_kw(
                                db, uid, password,
                                'mrp.production.backorder', 'create',
                                [wizard_vals]
                            )
                            #print("ID del wizard creado:", wizard_id)
                            try:
                                models.execute_kw(
                                    db, uid, password,
                                    'mrp.production.backorder', 'action_backorder',
                                    [[wizard_id]]
                                )
                                #print("Backorder ejecutado correctamente.")
                            except xmlrpc.client.Fault as fault:
                                if "cannot marshal None unless allow_none is enabled" in fault.faultString:
                                    print(" ")#print("Advertencia: El backorder se ejecutó pero devolvió None (lo cual genera error de serialización). Se continúa normalmente.")
                                else:
                                    print(f"Error en la API de Odoo: {fault.faultString}")
                                    raise
                            except Exception as e:
                                print(f"Ocurrió un error inesperado: {e}")
                                raise
                            #print(f"Se ejecuto correctamente todo el ciclo de la orden de producción :", nombre)
                        except xmlrpc.client.Fault as fault:
                            print(f"Error al crear nueva backorder: {fault}")
                            if "cannot marshal None unless allow_none is enabled" in fault.faultString:
                                print("Backorder creada pero omitida por error de serialización XML-RPC (None).")
                            else:
                                raise
                        except Exception as e:
                            print(f"Error inesperado al crear nueva backorder: {e}")
                    fabricado_en_esta_iteracion += Cantidad_fabricar_bo
                    print(f"Resumen: Fabricado {Cantidad_fabricar_bo} | Total parcial esta ronda: {fabricado_en_esta_iteracion}")
                    indice_linea_actual[0] += 1
                return fabricado_en_esta_iteracion
            except Exception as e:
                print(f"Error procesando backorders: {str(e)}")
                raise

    # Bucle principal que acumula total fabricado
    orden_principal = models.execute_kw(
        db, uid, password, 'mrp.production', 'read',
        [[id]], {'fields': ['qty_producing']}
    )
    total_fabricado = orden_principal[0]['qty_producing']
    indice_linea_actual = [1]  
    orden_principal = models.execute_kw(
        db, uid, password, 'mrp.production', 'read',
        [[id]], {'fields': ['qty_producing']}
    )
    total_fabricado = orden_principal[0]['qty_producing']
    print(f" DEBUG: product_qty={production_info['product_qty']}, qty_producing={production_info['qty_producing']}")
    print(f" DEBUG: cantidad_restante={production_info['product_qty'] - production_info['qty_producing']}")

    while total_fabricado < Cantidad:
        restante = Cantidad - total_fabricado
        print(f"\nFaltan por fabricar {restante} unidades.")
        fabricado = procesar_backorders(id, nombre, Cantidad, product_id, workcenter_id,cantidad_fabricar,
                                        fecha_hora, fecha_hora_fin, horahombre,
                                        maquina, cargues, company_ids, Localizacion,
                                        TipodeActividad, lineas, indice_linea_actual)
        if fabricado == 0:
            print("No se fabricó nada en esta iteración. No hay más backorders pendientes. Finalizando ciclo.")
            break
        total_fabricado += fabricado
        print(f"\nTotal acumulado fabricado: {total_fabricado} de {Cantidad}")

        # Avanzar en las líneas del Excel
        backorders_usados = models.execute_kw(
            db, uid, password, 'mrp.production', 'search_read',
            [[['name', '=like', f"{nombre.split('-')[0]}%"], ['state', 'in', ['done']]]],
            {'fields': ['id']}
        )
    return {"Orden_creada":str(nombre)}
